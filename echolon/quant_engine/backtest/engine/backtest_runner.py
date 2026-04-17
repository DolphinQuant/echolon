"""
Backtest Runner
===============

High-level orchestrator for running single backtests with full features.

Used for:
- Debug mode: Quick iteration with DEFAULT_PARAMS
- Best Trial mode: Run with optimized parameters

Features:
- Full CSV strategy logging
- Result saving (JSON, trades CSV, equity curve)
- Detailed metrics collection
- Contract-aware broker for futures

For optimization (many parallel runs), use OptimizationRunner instead.

Usage:
    from echolon.config.markets.factory import MarketFactory

    # Get TradingContext (single source of truth)
    ctx = MarketFactory.from_session()

    # Debug backtest
    results = BacktestRunner.debug(ctx)

    # Best trial backtest
    results = BacktestRunner.best_trial(ctx)

    # Custom parameters
    runner = BacktestRunner(ctx)
    runner.load_data()
    results = runner.run(params=my_params, context='custom')
"""

import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional

import pandas as pd

from .backtrader_engine import BacktestResults
from .enriched_pandas_data import EnrichedPandasData
from ...engine_factory import EngineFactory
from ...reporting import convert_to_serializable, save_trade_log, save_equity_curve
from ...data_loader.SHFE_loader import load_backtest_data, load_indicator_metadata, load_best_params
def _get_default_params():
    """Lazy load DEFAULT_PARAMS from platform_agnostic (single-instrument mode only)."""
    from pathlib import Path
    from echolon.quant_engine.strategy.loader import StrategyLoader
    from echolon.config.quant_engine import PLATFORM_AGNOSTIC_DIR
    loader = StrategyLoader(Path(PLATFORM_AGNOSTIC_DIR))
    return loader.load_attr("strategy_params", "DEFAULT_PARAMS")
from ...calculate_mfe_mae import enrich_trades_with_mfe_mae
from ...schemas.backtest_results import BacktestResultsSchemaV4
from .backtrader_strategy import get_strategy_class
from echolon.config.settings import PROJECT_ROOT
from echolon.config.quant_engine import (
    INDICATOR_DIR,
    MARKET_DATA_DIR,
)
from echolon.config.markets.core.context import TradingContext
from echolon.config.backtest_config import BacktestConfig
from ...logging_utils import (
    setup_backtest_logging,
    log_workflow_start,
    log_workflow_success,
    log_workflow_failure,
    log_result_summary,
    log_zero_trades_warning,
    get_run_context,
)

logger = logging.getLogger(__name__)


# =============================================================================
# Configuration
# =============================================================================

@dataclass
class _RunnerConfig:
    """Internal runner options (paths + feature flags).

    Not part of the public API — use the Pydantic ``BacktestConfig`` from
    ``echolon.config.backtest_config`` for external configuration.
    """
    # Paths - use centralized config from config/quant_engine.py
    indicator_dir: str = INDICATOR_DIR  # workspace/data/indicators/backtest/
    market_data_dir: str = MARKET_DATA_DIR  # workspace/data/market_data/
    output_dir: str = "workspace/current/backtest"

    # Features
    enable_strategy_logging: bool = True


# =============================================================================
# BacktestRunner Class
# =============================================================================

class BacktestRunner:
    """
    Full-featured backtest runner for single runs.

    Handles data loading, engine creation, backtest execution,
    and result saving. Optimized for debug and best_trial modes.

    For optimization (parallel runs), use OptimizationRunner instead.

    Parameters
    ----------
    ctx : TradingContext
        Trading context with market, instrument, and frequency configuration.
        This is the single source of truth for all trading parameters.
    config : _RunnerConfig, optional
        Internal runner options (paths + feature flags). Uses defaults if None.
    """

    def __init__(self, ctx: TradingContext, config: Optional[_RunnerConfig] = None,
                 strategy_code_dir: Optional[str] = None,
                 backtest_config: Optional[BacktestConfig] = None):
        """
        Initialize BacktestRunner with TradingContext.

        Args:
            ctx: TradingContext containing market, instrument, frequency info
            config: Optional _RunnerConfig for internal paths and feature flags.
            strategy_code_dir: Optional path to strategy code directory.
                If provided, strategy is loaded from this directory via importlib
                instead of from strategy/platform_agnostic/. Used by portfolio
                backtest to run per-slot strategies.
            backtest_config: Pydantic ``BacktestConfig`` providing date
                ranges, data paths, and drawdown thresholds.  Required.
        """
        if backtest_config is None:
            raise ValueError(
                "backtest_config is required. Build one with BacktestConfig(...) "
                "or use echolon.quick_start() for defaults."
            )
        self._backtest_config = backtest_config

        self.ctx = ctx
        self.config = config or _RunnerConfig()
        self.strategy_code_dir = strategy_code_dir

        # State
        self._indicators: Optional[pd.DataFrame] = None
        self._trading_calendar: Optional[pd.DataFrame] = None
        self._metadata: Optional[Dict[str, Any]] = None
        self._data_loaded = False

    # =========================================================================
    # Properties for convenient access
    # =========================================================================

    @property
    def market(self) -> str:
        """Market code (e.g., 'SHFE', 'CRYPTO')."""
        return self.ctx.market_code

    @property
    def instrument(self) -> str:
        """Instrument name (e.g., 'aluminum', 'bitcoin')."""
        return self.ctx.instrument_name

    @property
    def instrument_code(self) -> str:
        """Instrument code (e.g., 'al', 'btc')."""
        return self.ctx.instrument_code

    # =========================================================================
    # Data Loading
    # =========================================================================

    def load_data(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> 'BacktestRunner':
        """
        Load indicators and trading calendar using shared data loader utilities.

        Parameters
        ----------
        start_date : str, optional
            Override config start date
        end_date : str, optional
            Override config end date

        Returns
        -------
        BacktestRunner
            Self for method chaining
        """
        start_date = start_date or self._backtest_config.start_date
        end_date = end_date or self._backtest_config.end_date

        # Load data — per-slot dir if strategy_code_dir set, else default
        if self.strategy_code_dir:
            slot_name = Path(self.strategy_code_dir).name
            slot_ind_dir = Path(self.config.indicator_dir) / slot_name
            slot_csv = slot_ind_dir / "strategy_indicators.csv"
            if slot_csv.exists():
                self._indicators, self._trading_calendar = load_backtest_data(
                    ctx=self.ctx, indicators_path=str(slot_csv)
                )
            else:
                # Fallback to default path
                self._indicators, self._trading_calendar = load_backtest_data(ctx=self.ctx)
        else:
            self._indicators, self._trading_calendar = load_backtest_data(ctx=self.ctx)

        # Sort index for proper slicing (intraday data has non-unique dates)
        self._indicators = self._indicators.sort_index()

        # Filter to backtest period using boolean indexing for non-monotonic index
        start_ts = pd.Timestamp(start_date)
        end_ts = pd.Timestamp(end_date)
        self._indicators = self._indicators[
            (self._indicators.index >= start_ts) & (self._indicators.index <= end_ts)
        ].copy()

        if self._indicators.empty:
            raise ValueError(f"No data for period {start_date} to {end_date}")

        # Load metadata — per-slot dir if strategy_code_dir set, else default
        if self.strategy_code_dir:
            slot_name = Path(self.strategy_code_dir).name
            slot_meta = Path(self.config.indicator_dir) / slot_name / "strategy_indicator_metadata.json"
            if slot_meta.exists():
                self._metadata = load_indicator_metadata(ctx=self.ctx, metadata_path=str(slot_meta))
            else:
                self._metadata = load_indicator_metadata(ctx=self.ctx)
        else:
            self._metadata = load_indicator_metadata(ctx=self.ctx)

        self._data_loaded = True

        logger.info(
            f"[BACKTEST_RUNNER] Data loaded | "
            f"rows={len(self._indicators)}, period={start_date} to {end_date}"
        )

        return self

    # =========================================================================
    # Backtest Execution
    # =========================================================================

    def run(
        self,
        params: Dict[str, Any],
        context: str = 'debug',
        save_results: bool = True,
    ) -> Dict[str, Any]:
        """
        Run backtest with provided parameters.

        Parameters
        ----------
        params : Dict[str, Any]
            Strategy parameters
        context : str
            Run context: 'debug', 'best_trial', 'custom'
        save_results : bool
            Whether to save results to files

        Returns
        -------
        Dict[str, Any]
            Detailed results dictionary
        """
        if not self._data_loaded:
            self.load_data()

        # Setup context-aware logging
        run_context = "debug" if context == "debug" else "best_trial"
        setup_backtest_logging(run_context)

        # Log workflow start
        log_workflow_start(
            context=run_context,
            workflow="Backtest",
            market=self.market,
            instrument=self.instrument,
            bars=len(self._indicators),
        )

        # Setup paths
        output_dir = PROJECT_ROOT / self.config.output_dir
        # Indicator directory for contract-aware broker
        # Default: {indicator_dir}/{instrument}/by_contract/
        # Per-slot: {indicator_dir}/{slot_id}/by_contract/ (when strategy_code_dir set)
        if self.strategy_code_dir:
            slot_name = Path(self.strategy_code_dir).name
            indicator_dir = str(Path(self.config.indicator_dir) / slot_name)
        else:
            indicator_dir = str(Path(self.config.indicator_dir) / self.instrument)

        # Strategy logging directory
        strategy_log_dir = None
        if self.config.enable_strategy_logging:
            strategy_log_dir = str(output_dir / f"strategy_logs_{context}")
            os.makedirs(strategy_log_dir, exist_ok=True)

        # Create engine using factory with TradingContext
        engine = EngineFactory.create_backtest_engine(
            ctx=self.ctx,
            indicators_dir=indicator_dir,
            strategy_logger_enabled=self.config.enable_strategy_logging,
            strategy_logger_dir=strategy_log_dir,
        )

        # Create data feed class from metadata, then instantiate
        DataFeedClass = EnrichedPandasData.from_metadata(self._metadata)
        data_feed = DataFeedClass(dataname=self._indicators)

        # Get strategy class using ctx (with optional custom code dir)
        strategy_class = get_strategy_class(
            ctx=self.ctx, strategy_code_dir=self.strategy_code_dir
        )

        # Extract regime data for trade analyzers (regime attribution fix - BUG_001)
        regime_data = None
        if 'market_regime' in self._indicators.columns:
            regime_data = self._indicators[['market_regime']].reset_index()
            regime_data.columns = ['trading_date', 'market_regime']
            logger.debug(f"Regime data extracted for analyzers: {len(regime_data)} records")

        # Setup and run (commission, slippage, multiplier auto-retrieved from market_adapter)
        engine.setup(
            data_feed=data_feed,
            strategy_class=strategy_class,
            strategy_params=params,
            regime_data=regime_data,  # BUG_001 fix: pass regime data to analyzers
        )

        results = engine.run()

        # Build detailed results
        detailed_results = self._build_results(results, strategy_log_dir)

        # Log summary
        self._log_summary(results, context)

        # Save results
        if save_results:
            self._save_results(detailed_results, params, context, output_dir)

        return detailed_results

    def _build_results(
        self,
        results: BacktestResults,
        strategy_log_dir: Optional[str],
    ) -> Dict[str, Any]:
        """Build detailed results dictionary with MFE/MAE enrichment."""
        detailed = {
            'sharpe_ratio_annual': results.sharpe_ratio,
            'total_return_pct': results.total_return,
            'max_drawdown_pct': results.max_drawdown,
            'total_trades': results.total_trades,
            'winning_trades': results.winning_trades,
            'losing_trades': results.losing_trades,
            'win_rate_pct': (
                results.winning_trades / results.total_trades * 100
                if results.total_trades > 0 else 0
            ),
            'initial_value': results.initial_value,
            'final_value': results.final_value,
        }

        # Add analyzer results (includes trades and equity_curve)
        detailed.update(results.analyzers)

        # Enrich trades with MFE/MAE metrics for exit quality analysis
        # This enables downstream ExitEffectivenessAnalyzer to work
        if 'trades' in detailed and detailed['trades']:
            trades_list = detailed['trades']
            if isinstance(trades_list, dict) and 'trades' in trades_list:
                # Handle wrapped format: {'trades': [...]}
                enriched = enrich_trades_with_mfe_mae(
                    trades_list=trades_list['trades'],
                    ctx=self.ctx
                )
                detailed['trades'] = {'trades': enriched}
            elif isinstance(trades_list, list):
                # Handle direct list format
                enriched = enrich_trades_with_mfe_mae(
                    trades_list=trades_list,
                    ctx=self.ctx
                )
                detailed['trades'] = enriched

        # Add log directory
        if strategy_log_dir:
            detailed['strategy_log_dir'] = strategy_log_dir

        return detailed

    def _log_summary(self, results: BacktestResults, context: str) -> None:
        """Log results summary with SUCCESS/FAILURE markers."""
        run_context = get_run_context()

        # Check for zero trades - critical diagnostic
        if results.total_trades == 0:
            log_zero_trades_warning(
                run_context,
                "Backtest",
                bars_processed=len(self._indicators),
                entry_signals_generated=0,  # Would need strategy stats
                entry_signals_blocked=0,
                risk_blocks=0,
            )
            log_workflow_failure(
                run_context,
                "Backtest",
                "Zero trades executed - check entry/risk conditions"
            )
            return

        # Log result summary (CRITICAL level for debugger_agent)
        win_rate = (
            results.winning_trades / results.total_trades * 100
            if results.total_trades > 0 else 0
        )
        log_result_summary(
            run_context,
            "Backtest",
            sharpe=results.sharpe_ratio or 0,
            total_return=results.total_return or 0,
            max_drawdown=results.max_drawdown or 0,
            num_trades=results.total_trades,
            win_rate=win_rate,
        )

        # Log SUCCESS marker
        log_workflow_success(
            run_context,
            "Backtest",
            sharpe=f"{results.sharpe_ratio:.3f}" if results.sharpe_ratio else "N/A",
            total_return=f"{results.total_return:.2f}%",
            trades=results.total_trades,
        )

        # Also log at INFO level for compatibility
        sharpe = f"{results.sharpe_ratio:.3f}" if results.sharpe_ratio else "N/A"
        max_dd = f"{results.max_drawdown:.2f}%" if results.max_drawdown else "N/A"

        logger.info(
            f"[BACKTEST_RUNNER] Complete | context={context}, "
            f"sharpe={sharpe}, return={results.total_return:.2f}%, "
            f"max_dd={max_dd}, trades={results.total_trades}"
        )

    def _save_results(
        self,
        results: Dict[str, Any],
        params: Dict[str, Any],
        context: str,
        output_dir: Path,
    ) -> None:
        """Save results to files using reporting utilities."""
        os.makedirs(output_dir, exist_ok=True)

        # Build results data structure
        results_data = {
            "schema_version": "4.0",
            "run_timestamp": datetime.now().isoformat(),
            "run_context": context,
            "market": self.market,
            "instrument": self.instrument,
            "instrument_code": self.instrument_code,
            "performance_metrics": convert_to_serializable({
                k: v for k, v in results.items()
                if k not in ['trades', 'equity_curve', 'strategy_log_dir']
            }),
            "strategy_parameters": convert_to_serializable(params),
        }

        # Validate against schema before saving (fail-fast)
        validated = BacktestResultsSchemaV4.model_validate(results_data)
        logger.info(f"[BACKTEST_RUNNER] Schema validated | version={validated.schema_version}")

        results_path = output_dir / "backtest_results.json"
        with open(results_path, 'w') as f:
            json.dump(validated.model_dump(), f, indent=4, default=str)

        logger.info(f"[BACKTEST_RUNNER] Results saved | path={results_path}")

        # Save trade log using reporting utility
        if 'trades' in results and results['trades']:
            trades_path = str(output_dir / "backtest_trades.csv")
            save_trade_log(results['trades'], trades_path)

        # Save equity curve using reporting utility
        if 'equity_curve' in results and results['equity_curve']:
            equity_path = str(output_dir / "equity_curve.csv")
            save_equity_curve(results['equity_curve'], equity_path)

    # =========================================================================
    # Convenience Class Methods
    # =========================================================================

    @classmethod
    def debug(
        cls,
        ctx: TradingContext,
        backtest_config: Optional[BacktestConfig] = None,
    ) -> Dict[str, Any]:
        """
        Run debug backtest with DEFAULT_PARAMS.

        Convenience method for quick strategy iteration.

        Parameters
        ----------
        ctx : TradingContext
            Trading context (single source of truth)
        backtest_config : BacktestConfig, optional
            Pydantic config with date ranges, paths, and thresholds.  Required.

        Returns
        -------
        Dict[str, Any]
            Detailed results
        """
        runner = cls(ctx, backtest_config=backtest_config)
        runner.load_data()
        return runner.run(_get_default_params(), context='debug')

    @classmethod
    def best_trial(
        cls,
        ctx: TradingContext,
        params_path: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        strategy_code_dir: Optional[str] = None,
        backtest_config: Optional[BacktestConfig] = None,
    ) -> Dict[str, Any]:
        """
        Run backtest with best parameters from optimization.

        Loads parameters from selected_robust_trial.json.

        Parameters
        ----------
        ctx : TradingContext
            Trading context (single source of truth)
        params_path : str, optional
            Path to parameters JSON. Uses default if None.
        start_date : str, optional
            Override backtest start date (e.g. OOS_START_DATE for out-of-sample).
        end_date : str, optional
            Override backtest end date (e.g. OOS_END_DATE for out-of-sample).
        strategy_code_dir : str, optional
            Path to strategy code directory. If provided, loads strategy
            from this directory instead of platform_agnostic/.
        backtest_config : BacktestConfig, optional
            Pydantic config with date ranges, paths, and thresholds.
            Falls back to module globals if not provided.

        Returns
        -------
        Dict[str, Any]
            Detailed results
        """
        runner = cls(
            ctx,
            strategy_code_dir=strategy_code_dir,
            backtest_config=backtest_config,
        )

        # Default params path — from slot dir if provided, else platform_agnostic
        if params_path is None:
            if strategy_code_dir:
                params_path = str(Path(strategy_code_dir) / "selected_robust_trial.json")
            else:
                from echolon.config.quant_engine import BEST_PARAMS_FILE
                params_path = BEST_PARAMS_FILE

        # Load and map parameters using shared utility
        params_data = load_best_params(params_path)
        optuna_params = params_data.get('params', params_data)

        # Load DEFAULT_PARAMS from slot dir if custom, else platform_agnostic
        if strategy_code_dir:
            from echolon.quant_engine.strategy.loader import StrategyLoader
            loader = StrategyLoader(Path(strategy_code_dir))
            slot_defaults = loader.load_attr("strategy_params", "DEFAULT_PARAMS")
        else:
            slot_defaults = _get_default_params()
        strategy_params = cls._map_optuna_params(optuna_params, slot_defaults)

        return runner.load_data(start_date=start_date, end_date=end_date).run(
            strategy_params, context='best_trial'
        )

    @staticmethod
    def _map_optuna_params(
        optuna_params: Dict[str, Any],
        default_params: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Map Optuna flat parameters to strategy component structure."""
        entry_params = {}
        exit_params = {}
        sizer_params = {}
        risk_params = {}
        strategy_params = {}

        metadata_fields = {
            'run_timestamp', 'study_name', 'best_trial_number', 'best_value',
            'datetime_start', 'datetime_complete'
        }

        for key, value in optuna_params.items():
            if key in metadata_fields:
                continue

            if key.startswith('entry_'):
                entry_params[key[6:]] = value
            elif key.startswith('exit_'):
                exit_params[key[5:]] = value
            elif key.startswith('sizer_'):
                sizer_params[key[6:]] = value
            elif key.startswith('risk_'):
                risk_params[key[5:]] = value
            else:
                strategy_params[key] = value

        # Fill missing from defaults
        component_mapping = {
            'entry_params': entry_params,
            'exit_params': exit_params,
            'sizer_params': sizer_params,
            'risk_params': risk_params
        }

        for comp_key, default_comp in default_params.items():
            if comp_key in component_mapping and isinstance(default_comp, dict):
                target = component_mapping[comp_key]
                for param_name, param_value in default_comp.items():
                    if param_name not in target:
                        target[param_name] = param_value

        return {
            **strategy_params,
            'entry_params': entry_params,
            'exit_params': exit_params,
            'sizer_params': sizer_params,
            'risk_params': risk_params,
        }
