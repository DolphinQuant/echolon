"""
Walk-Forward Analysis Runner
=============================

Orchestrates walk-forward analysis across multiple expanding windows.

For each window:
1. Filter indicators to IS period
2. Run Optuna optimization (N trials)
3. Select best robust trial via TrialSelector
4. Run OOS backtest with selected trial params
5. Collect IS/OOS metrics

After all windows:
6. Compute WFA aggregate metrics
7. Run final full-period backtest with last window's parameters
8. Augment backtest_results.json with WFA fields
"""

import gc
import json
import logging
import shutil
from pathlib import Path
from typing import Dict, Any, Optional

import pandas as pd

from echolon.config.markets.core.context import TradingContext
from echolon.config.optuna_config import OptunaConfig
from echolon.config.backtest_config import BacktestConfig
from echolon.errors import raise_error
from .window import WFAWindow, WFAConfig
from .analyzer import WalkForwardAnalyzer
from .drs_calculator import compute_drs, DRSConfig

logger = logging.getLogger(__name__)


class WFARunner:
    """
    Orchestrates walk-forward analysis across multiple windows.

    Each window gets independent Optuna optimization + TrialSelector + OOS backtest.
    After all windows, a final full-period backtest runs with the last window's
    parameters, and WFA robustness metrics are added to the results.
    """

    def __init__(
        self,
        ctx: TradingContext,
        config: WFAConfig,
        optuna_config: Optional[OptunaConfig] = None,
        backtest_config: Optional[BacktestConfig] = None,
        backtest_results_dir: Optional[Path] = None,
        paths: Optional["PathsConfig"] = None,  # type: ignore[name-defined]
        drs_config: Optional[DRSConfig] = None,
    ):
        if optuna_config is None:
            raise ValueError(
                "optuna_config is required. Build one with OptunaConfig(...) "
                "or use echolon.quick_start() for defaults."
            )
        self._optuna_config = optuna_config

        if backtest_config is None:
            raise ValueError(
                "backtest_config is required. Build one with BacktestConfig(...) "
                "or use echolon.quick_start() for defaults."
            )
        self._backtest_config = backtest_config

        self.ctx = ctx
        self.config = config
        from echolon.config.paths_config import PathsConfig
        self._paths = paths if paths is not None else PathsConfig.from_env()
        if backtest_results_dir is None:
            backtest_results_dir = self._paths.backtest_results_dir
        self.output_dir = Path(backtest_results_dir)
        self.wfa_dir = self.output_dir / "wfa_windows"

        # Caller provides DRSConfig explicitly (or None to run WFA without DRS
        # scoring). Host apps build this from their own target schema — echolon
        # no longer reaches into ctx.target workflow state.
        self._drs_config = drs_config

    def run(self) -> Dict[str, Any]:
        """
        Run complete WFA pipeline.

        Returns:
            Dict with final backtest_results.json content including WFA fields.
        """
        # Deferred imports (after cache clearing in orchestrator)
        from echolon.backtest.optimization.optuna_study import OptunaOptimizer
        from echolon.backtest.optimization.select_best_trial import TrialSelector
        from echolon.backtest.runner import run_best_trial
        from echolon.engine.factory import EngineFactory
        from echolon.backtest.engine.backtrader_strategy import get_strategy_class
        from echolon.data.loaders.backtest_data_loader import (
            load_backtest_data, load_indicator_metadata
        )
        # Load strategy_params dynamically from the configured strategy code
        # directory (workspace/current/code/strategy_params.py). StrategyLoader
        # handles the file-path → module resolution; a static import would
        # hardcode a pre-v0.3 path that no longer exists.
        from echolon.strategy.loader import StrategyLoader as _StrategyLoader
        _sp_loader = _StrategyLoader(self._paths.strategy_code_dir)
        _sp = _sp_loader.load_module("strategy_params")
        optuna_search_space = _sp.optuna_search_space
        DEFAULT_PARAMS = _sp.DEFAULT_PARAMS
        apply_shared_params = _sp.apply_shared_params
        framework = _sp.framework

        # Clean stale backtest artefacts from the prior run before starting
        # a fresh WFA pass. Previously delegated to qorka's
        # ``lib.file_operation.clean_backtest_folder`` — inlined here to
        # remove the host-app dependency; the cleanup target is
        # ``self._paths.backtest_results_dir`` (already injected).
        _stale_artefacts = [
            "backtest_results.json",
            "backtest_trades.csv",
            "equity_curve.csv",
            "optimization_trials.csv",
            "full_trial_selection_record.json",
            "optuna_study_info.json",
        ]
        for _name in _stale_artefacts:
            _p = Path(self.output_dir) / _name
            if _p.exists():
                _p.unlink()
                logger.info(f"[WFA] cleaned stale artefact: {_name}")

        # Load full indicators ONCE (covers entire date range)
        full_indicators, trading_calendar_df = load_backtest_data(ctx=self.ctx)
        indicator_metadata = load_indicator_metadata(ctx=self.ctx)
        if not isinstance(full_indicators.index, pd.DatetimeIndex):
            full_indicators.index = pd.to_datetime(full_indicators.index)
        full_indicators = full_indicators.sort_index()

        # Create market adapter and strategy class ONCE
        market_adapter = EngineFactory.create_market_adapter(ctx=self.ctx, mode="backtest")
        strategy_class = get_strategy_class(ctx=self.ctx)

        # Create per-window storage
        self.wfa_dir.mkdir(parents=True, exist_ok=True)

        for window in self.config.windows:
            logger.info(
                f"\n{'='*80}\n"
                f"WFA WINDOW {window.window_id}: "
                f"IS={window.is_start} -> {window.is_end}, "
                f"OOS={window.oos_start} -> {window.oos_end}\n"
                f"{'='*80}"
            )
            print(
                f"\n{'='*80}\n"
                f"WFA WINDOW {window.window_id}/{len(self.config.windows)}: "
                f"IS={window.is_start} -> {window.is_end}, "
                f"OOS={window.oos_start} -> {window.oos_end}\n"
                f"{'='*80}"
            )

            window_dir = self.wfa_dir / f"window_{window.window_id}"
            window_dir.mkdir(parents=True, exist_ok=True)

            # --- Step 1: Filter IS data ---
            is_start_ts = pd.Timestamp(window.is_start)
            is_end_ts = pd.Timestamp(window.is_end)
            is_indicators = full_indicators[
                (full_indicators.index >= is_start_ts) &
                (full_indicators.index <= is_end_ts)
            ].copy()

            if is_indicators.empty:
                logger.warning(f"Window {window.window_id}: No IS data, skipping")
                continue

            logger.info(
                f"Window {window.window_id}: IS data "
                f"{is_indicators.index[0].date()} -> {is_indicators.index[-1].date()}, "
                f"{len(is_indicators)} bars"
            )

            # --- Step 2: Run Optuna optimization on IS ---
            optimizer = OptunaOptimizer(
                ctx=self.ctx,
                market_adapter=market_adapter,
                strategy_class=strategy_class,
                search_space_fn=optuna_search_space,
                n_trials=self.config.trials_per_window,
                optimization_target=self.config.optimization_target,
                run_context="optimization",
                optuna_config=self._optuna_config,
            )

            study, _best_params = optimizer.run(
                indicators=is_indicators,
                trading_calendar_df=trading_calendar_df,
                study_name=f"WFA_window_{window.window_id}",
                indicator_metadata=indicator_metadata,
                # Persist per-window trial_failure_summary.json alongside
                # optimization_trials.csv. LLM debugger agents consume this
                # as the canonical AI-readable breadcrumb.
                failure_report_dir=window_dir,
                failure_report_window_id=window.window_id,
            )

            # Save per-window optimization results
            if study:
                optimizer.save_study_results(
                    study=study,
                    output_dir=str(window_dir),
                    save_trials_csv=True,
                    save_best_params=True,
                )

            # Extract IS sharpe from study
            window.is_sharpe = self._extract_is_sharpe(study)

            # --- Step 3: Select robust trial ---
            trials_csv_path = window_dir / "optimization_trials.csv"
            if not trials_csv_path.exists():
                logger.warning(f"Window {window.window_id}: No trials CSV, skipping")
                continue

            selector = TrialSelector(
                trial_data_path=str(trials_csv_path),
                output_dir=str(window_dir),
                max_drawdown_threshold=self.config.max_drawdown_threshold,
                default_params=DEFAULT_PARAMS,
                apply_shared_params_fn=apply_shared_params,
                param_classifications=framework.get_param_classifications(),
            )
            selected_trial = selector.select()
            window.selected_trial = selected_trial

            if not selected_trial:
                logger.warning(f"Window {window.window_id}: No robust trial found, skipping OOS")
                continue

            logger.info(
                f"Window {window.window_id}: Selected trial "
                f"#{selected_trial.get('trial_number', '?')} from "
                f"cluster {selected_trial.get('cluster_id', '?')}"
            )

            # --- Step 4: Run OOS backtest ---
            # TrialSelector saves selected_robust_trial.json to the strategy
            # code directory (PathsConfig.strategy_code_dir) — which is what
            # run_best_trial reads by default.
            oos_results = run_best_trial(
                ctx=self.ctx,
                start_date=window.oos_start,
                end_date=window.oos_end,
                backtest_config=self._backtest_config,
            )

            window.oos_results = oos_results
            window.oos_sharpe = oos_results.get('sharpe_ratio_annual', 0.0)

            # --- Step 5: Archive per-window OOS artifacts ---
            self._archive_window_artifacts(window, window_dir)

            wfe_str = (
                f"{window.walk_forward_efficiency:.3f}"
                if window.walk_forward_efficiency is not None else "N/A"
            )
            logger.info(
                f"Window {window.window_id}: "
                f"IS_sharpe={window.is_sharpe:.3f}, "
                f"OOS_sharpe={window.oos_sharpe:.3f}, "
                f"WFE={wfe_str}"
            )
            print(
                f"Window {window.window_id} complete: "
                f"IS_sharpe={window.is_sharpe:.3f}, "
                f"OOS_sharpe={window.oos_sharpe:.3f}, "
                f"WFE={wfe_str}"
            )

            # Memory cleanup between windows
            del is_indicators, study
            gc.collect()

        # --- Step 6: Compute WFA metrics from per-window OOS results ---
        completed_windows = [w for w in self.config.windows if w.oos_results is not None]

        if not completed_windows:
            # Loud failure — previously this was a silent ``return {}`` which
            # let the host app (qorka's main.py) exit zero with no artifacts.
            # Every window's ``trial_failure_summary.json`` already carries
            # the structured root cause; WFA-001 simply stops the pipeline
            # and points the user/agent at those breadcrumbs.
            logger.error("WFA: No windows completed successfully — raising WFA-001")
            raise_error(
                "WFA-001",
                n_windows=len(self.config.windows),
                reason="All WFA windows produced zero valid trials",
                suggestion=(
                    f"See per-window trial_failure_summary.json under {self.wfa_dir}"
                ),
            )

        wfa_analyzer = WalkForwardAnalyzer(completed_windows)
        wfa_summary = wfa_analyzer.compute_summary()
        wfa_window_details = wfa_analyzer.compute_window_details()

        # --- Step 7: Final full-period backtest with last window's params ---
        # Last window's TrialSelector already saved selected_robust_trial.json
        # to the strategy code directory (PathsConfig.strategy_code_dir).
        # run_best_trial() reads from there by default and backtests across
        # the full BACKTEST_START_DATE → BACKTEST_END_DATE.
        # This produces consistent performance_metrics, trades, and equity curve
        # all from one parameter set — no artificial stitching.
        logger.info(
            "Running final full-period backtest with last window's parameters..."
        )
        print(
            "\n" + "="*80 + "\n"
            "FINAL FULL-PERIOD BACKTEST (with last window's robust parameters)\n"
            + "="*80
        )
        run_best_trial(ctx=self.ctx, backtest_config=self._backtest_config)

        # --- Step 8: Augment backtest_results.json with WFA fields ---
        last_window = completed_windows[-1]
        final_results = self._build_final_results(
            last_window=last_window,
            wfa_summary=wfa_summary,
            wfa_window_details=wfa_window_details,
        )

        drs_score = final_results.get('drs', {}).get('drs_score', 0) or 0
        logger.info(
            f"\nWFA COMPLETE: {len(completed_windows)}/{len(self.config.windows)} windows, "
            f"OOS Sharpe mean={(wfa_summary.get('oos_sharpe_mean') or 0):.3f}, "
            f"WFE mean={(wfa_summary.get('wfe_mean') or 0):.3f}, "
            f"DRS={drs_score:.1f}/100"
        )

        return final_results

    def _extract_is_sharpe(self, study) -> float:
        """Extract the best IS sharpe from the Optuna study."""
        if study is None:
            return 0.0

        completed = [t for t in study.trials if t.state.name == 'COMPLETE']
        if not completed:
            return 0.0

        # For multi-objective, values[0] is sharpe_ratio
        best_sharpe = max(t.values[0] for t in completed)
        return float(best_sharpe)

    def _archive_window_artifacts(self, window: WFAWindow, window_dir: Path):
        """
        Copy OOS backtest artifacts from workspace/current/backtest/ to
        per-window directory for record-keeping.
        """
        src_dir = self.output_dir
        for filename in ["backtest_results.json", "backtest_trades.csv", "equity_curve.csv"]:
            src = src_dir / filename
            if src.exists():
                dst = window_dir / f"oos_{filename}"
                shutil.copy2(str(src), str(dst))

    def _build_final_results(
        self,
        last_window: WFAWindow,
        wfa_summary: Dict[str, Any],
        wfa_window_details: list,
    ) -> Dict[str, Any]:
        """
        Augment the full-period backtest_results.json with WFA fields.

        At this point, run_best_trial() has already written consistent
        backtest_results.json, backtest_trades.csv, and equity_curve.csv
        from the full-period backtest. We just add WFA robustness data.
        """
        results_path = self.output_dir / "backtest_results.json"
        if results_path.exists():
            with open(results_path, 'r') as f:
                final_data = json.load(f)
        else:
            logger.error("No backtest_results.json from full-period backtest")
            final_data = {}

        # Add WFA fields (additive — does not touch performance_metrics)
        final_data["wfa_summary"] = wfa_summary
        final_data["wfa_windows"] = wfa_window_details

        # Compute Deployment Readiness Score from WFA + performance data.
        # Host app must inject drs_config via the constructor — echolon no
        # longer derives it from ctx.target workflow state.
        drs_result = compute_drs(final_data, config=self._drs_config)
        final_data["drs"] = drs_result.to_dict()

        # Copy last window's optimization_trials.csv to main backtest dir
        last_window_dir = self.wfa_dir / f"window_{last_window.window_id}"
        src_trials = last_window_dir / "optimization_trials.csv"
        if src_trials.exists():
            shutil.copy2(str(src_trials), str(self.output_dir / "optimization_trials.csv"))

        # Re-save augmented backtest_results.json
        with open(results_path, 'w') as f:
            json.dump(final_data, f, indent=4, default=str)

        logger.info(
            f"Final backtest_results.json augmented with "
            f"{len(wfa_window_details)} WFA window details"
        )
        return final_data
