"""
Parallel Indicator Processor

Optimized version of the indicator calculation workflow that:
1. Processes contract files in parallel via data_pipeline loaders
2. Uses the new TA-Lib indicator system (indicator_utils.py and indicator_mapping.py)
3. Converts data to numpy arrays for efficient calculation
4. Outputs indicators in the same format as the legacy system
5. Uses session-based context (SESSION_PHASE, VOLATILITY_STATE) for intraday
"""
import os
import pandas as pd
import numpy as np
from typing import List, Dict, Any, Optional
import logging
from multiprocessing import cpu_count
from multiprocessing.pool import ThreadPool
import time
from pathlib import Path
import json
from datetime import datetime

# Data pipeline loaders for standardized data access
from echolon.data_pipeline.loaders.ohlcv_loader import (
    load_contract_ohlcv,
    get_available_contracts,
)
# SHFE contract rules (main contract lookup, expiry date)
from echolon.quant_engine.market_adapters.shfe.contract_rules import get_main_contract, get_expiry_date
from echolon.data_pipeline.loaders.session_availability_loader import (
    get_session_availability_loader,
)
from ..registry.utils import get_indicator_info, get_function
from echolon.indicators.utils.indicator_loader import get_analysis_indicator_list
from echolon.quant_engine.types import validate_indicator_list_json
from echolon.config.settings import PROJECT_ROOT, OUTPUT_DIR
from echolon.config.markets.core.context import TradingContext
from echolon.config.quant_engine import MARKET_DATA_DIR

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Default volatility context parameters
DEFAULT_CONTEXT_PARAMS = {
    'atr_period': 14,
    'vol_lookback': 100,
    'high_percentile': 75.0,
    'low_percentile': 25.0,
}
 

class IndicatorProcessor:
    """
    Parallel processor for calculating TA-Lib indicators on contract data.
    Uses data_pipeline loaders for standardized data access.
    """

    def __init__(
        self,
        ctx: TradingContext,
        trading_date_list,
        output_dir: str = None,
        n_jobs: int = None,
        selected: bool = True,
        indicator_config: Optional[Dict[str, Any]] = None,
        regime_params: Optional[Dict[str, Any]] = None,
        backtest_start_year: Optional[int] = None,
    ):
        """
        Initialize the parallel processor.

        Args:
            ctx: TradingContext with market, instrument, frequency, bar_size configuration
            trading_date_list: List of trading dates to process
            output_dir: Directory to save processed indicator files
            n_jobs: Number of parallel processes (default: CPU count)
            selected: Whether to use selected indicators only
            indicator_config: Optional pre-loaded indicator config dict.
                If provided, used instead of loading from strategy_indicator_list.json.
            regime_params: Optional pre-loaded regime params dict.
                If provided, used instead of loading from output/regime_params.json
                or running Optuna optimization. Each strategy cluster has its own
                regime_params.json optimized on its instrument's data.
            backtest_start_year: Earliest year (e.g. 2018) used to filter contracts
                in :meth:`_is_contract_in_backtest_period`. Required only when
                ``selected`` is True and contracts must match the backtest period.
        """
        self._provided_regime_params = regime_params
        self._backtest_start_year = backtest_start_year
        # Store context for frequency-aware indicator parameters
        self.ctx = ctx

        # Extract values from context
        self.trading_date_list = trading_date_list
        self.market = ctx.market_code
        self.asset = ctx.instrument_name
        self.bar_size = ctx.bar_size
        self.bar_size_minutes = ctx.bar_size_minutes

        # Map frequency for internal use: interday -> "day", intraday -> "minute"
        self.frequency = "minute" if ctx.is_intraday else "day"

        self.output_dir = Path(output_dir)
        self.contract_output_dir = Path(output_dir) / "by_contract"
        self.n_jobs = n_jobs or cpu_count()
        self.selected = selected
        self.futures = self.asset  # Keep for backwards compatibility
        self.futures_code = ctx.instrument_code

        # Get frequency-scaled default parameters from context
        self.default_params = ctx.get_indicator_params()

        # Create output directory
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.contract_output_dir.mkdir(parents=True, exist_ok=True)

        # Load indicator configuration from strategy file or use provided config
        if selected:
            if indicator_config is not None:
                self.indicator_config = indicator_config
            else:
                self.indicator_config = self._load_strategy_indicators()
            self.indicator_keys = self._extract_indicator_keys()

        # Initialize regime/context parameters based on frequency
        # - Interday (daily): Use regime optimizer for 4-state model
        # - Intraday (minute): Use simple context params (no optimizer needed)
        if self.frequency == "day":
            if self._provided_regime_params is not None:
                # Use caller-provided regime params (per-slot portfolio backtest)
                self.regime_params = self._provided_regime_params
                if logger.isEnabledFor(logging.INFO):
                    logger.info("[INDICATOR_PROCESSOR] Using provided regime params (per-slot)")
            else:
                self.regime_params = self._initialize_regime_params()
            self.session_availability = None  # Not used for interday
        else:
            # Intraday uses session_phase + volatility_state (no optimization)
            # Use frequency-scaled context params from TradingContext
            self.regime_params = {
                'atr_period': self.default_params['atr_period'],
                'vol_lookback': self.default_params['vol_lookback'],
                'high_percentile': self.default_params['volatility_high_pct'],
                'low_percentile': self.default_params['volatility_low_pct'],
            }
            # Load session availability for bar count indicators
            # Use bar_size_minutes and bar_size from TradingContext for correct phase schema
            self.session_availability = get_session_availability_loader(
                market=self.market,
                instrument=self.asset,
                bar_size_minutes=self.bar_size_minutes,
                bar_size=self.bar_size  # Pass bar_size for aggregated phase detection
            )
            if logger.isEnabledFor(logging.INFO):
                logger.info(f"[INDICATOR_PROCESSOR] Session availability loaded | market={self.market}, instrument={self.asset}, bar_size={self.bar_size}")

        if logger.isEnabledFor(logging.INFO):
            logger.info(f"[INDICATOR_PROCESSOR] Initialized | market={self.market}, asset={self.asset}, freq={self.frequency}, bar_size={self.bar_size}")
            logger.info(f"[INDICATOR_PROCESSOR] Config | processes={self.n_jobs}, bar_size_minutes={self.bar_size_minutes}")
            logger.info(f"[INDICATOR_PROCESSOR] Output dir | path={self.output_dir}")

    def _initialize_regime_params(self, n_trials: int = 400) -> Dict:
        """
        Initialize regime classification parameters for INTERDAY (daily) data only.

        Strategy:
        1. Check if optimized params exist in output/regime_params.json
        2. If exists, load cached params
        3. If no cache exists, run optimization and save results

        Note: This is only called for interday (daily) frequency.
        Intraday uses session_phase + volatility_state instead.

        Args:
            n_trials: Number of Optuna trials for optimization

        Returns:
            Dict with regime classification parameters
        """
        # Default interday regime params
        DEFAULT_INTERDAY_REGIME_PARAMS = {
            'fast_ma_period': 20,
            'slow_ma_period': 50,
            'adx_period': 14,
            'adx_trend_threshold': 20.0,
            'atr_period': 14,
            'vol_lookback': 60,
            'vol_high_percentile': 75.0,
            'chop_period': 14,
            'chop_threshold': 50.0,
            'min_regime_bars': 3
        }

        # Use OUTPUT_DIR for regime params storage
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        params_file = OUTPUT_DIR / "regime_params.json"

        # Try to load cached params
        if params_file.exists():
            with open(params_file, 'r') as f:
                cached = json.load(f)

            if logger.isEnabledFor(logging.INFO):
                logger.info(f"[INDICATOR_PROCESSOR] Loaded cached regime params | path={params_file}")
                logger.info(f"[INDICATOR_PROCESSOR] Regime params | score={cached.get('score', 'N/A'):.4f}")

            return cached.get('params', DEFAULT_INTERDAY_REGIME_PARAMS)

        # Run optimization if no cache
        else:
            if logger.isEnabledFor(logging.INFO):
                logger.info(f"[INDICATOR_PROCESSOR] Running interday regime optimization | trials={n_trials}")

            optimized_params = self._run_regime_optimization(n_trials)

            if optimized_params:
                return optimized_params

        # Fallback to defaults
        if logger.isEnabledFor(logging.INFO):
            logger.info("[INDICATOR_PROCESSOR] Using default interday regime params")

        return DEFAULT_INTERDAY_REGIME_PARAMS.copy()

    def _run_regime_optimization(self, n_trials: int) -> Optional[Dict]:
        """
        Run regime classification optimization using Optuna.

        Only used for INTERDAY (daily) frequency.
        Intraday uses session_phase + volatility_state (no optimization needed).

        Args:
            n_trials: Number of optimization trials

        Returns:
            Optimized parameters dict, or None if optimization fails
        """
        import optuna

        # Suppress optuna verbosity
        optuna.logging.set_verbosity(optuna.logging.WARNING)

        # Compute data directory for regime optimizer
        # Path structure: workspace/data/market_data/{market}/{asset}/sort_by_contract/
        data_dir = os.path.join(MARKET_DATA_DIR, self.market, self.asset, "sort_by_contract")

        # Only interday regime optimization is supported
        # Intraday uses session_phase + volatility_state instead
        from ..optimization.interday_regime_optimizer import InterdayRegimeOptimizer, RegimeOptimizerConfig
        config = RegimeOptimizerConfig(n_trials=n_trials, seed=42)
        optimizer = InterdayRegimeOptimizer(
            data_dir=data_dir,
            config=config,
            futures=self.futures,
            market=self.market
        )
        logger.info(f"[INDICATOR_PROCESSOR] Using INTERDAY regime optimizer | freq={self.frequency}")

        # Run optimization
        best_params, study = optimizer.optimize(show_progress=False)

        # Validate results
        validation = optimizer.validate_params(best_params)

        # Save results to OUTPUT_DIR
        results = {
            'params': best_params,
            'score': study.best_value,
            'validation_passed': validation['validation_passed'],
            'metrics': validation['metrics'],
            'optimized_at': datetime.now().isoformat(),
            'n_trials': n_trials,
            'futures': self.futures
        }

        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        params_file = OUTPUT_DIR / "regime_params.json"
        with open(params_file, 'w') as f:
            json.dump(results, f, indent=2, default=str)

        if logger.isEnabledFor(logging.INFO):
            logger.info(f"[INDICATOR_PROCESSOR] Regime optimization complete | score={study.best_value:.4f}")
            logger.info(f"[INDICATOR_PROCESSOR] Saved regime params | path={params_file}")

        # Log key improvements
        comparison = optimizer.compare_with_default()
        improvement = comparison['improvement']
        if logger.isEnabledFor(logging.INFO):
            logger.info(f"[INDICATOR_PROCESSOR] Improvement over defaults:")
            logger.info(f"[INDICATOR_PROCESSOR]   Score: {improvement['score_pct_improvement']:+.1f}%")
            if 'return_separation_delta' in improvement:
                logger.info(f"[INDICATOR_PROCESSOR]   Return Separation: {improvement['return_separation_delta']:+.4f}%")
            if 'direction_alignment_delta' in improvement:
                logger.info(f"[INDICATOR_PROCESSOR]   Direction Alignment: {improvement['direction_alignment_delta']:+.2%}")

        return best_params

    def process_all_contracts(self, use_multiprocessing: bool = True) -> Dict[str, bool]:
        """
        Process all contract files
        
        Args:
            use_multiprocessing: Whether to use parallel processing
            
        Returns:
            Dictionary mapping contract names to success status
        """
        contract_files = self.get_contract_files()

        if not contract_files:
            logger.warning("[INDICATOR_PROCESSOR] No contracts found | action=skipping")
            return {}

        start_time = time.time()

        if use_multiprocessing and self.n_jobs > 1:
            if logger.isEnabledFor(logging.INFO):
                logger.info(f"[INDICATOR_PROCESSOR] Parallel processing | contracts={len(contract_files)}, threads={self.n_jobs}")

            # Use ThreadPool instead of Pool to avoid pickling issues with instance methods
            # when modules are reloaded in async contexts (e.g., main.py workflow)
            with ThreadPool(processes=self.n_jobs) as pool:
                results = pool.map(self.process_single_contract, contract_files)

            results_dict = dict(zip(contract_files, results))
        else:
            if logger.isEnabledFor(logging.INFO):
                logger.info(f"[INDICATOR_PROCESSOR] Sequential processing | contracts={len(contract_files)}")
            results_dict = {}
            
            for contract_name in contract_files:
                results_dict[contract_name] = self.process_single_contract(contract_name)
        
        main_contract = self.extract_main_contract_indicators(
                        trading_dates_list=self.trading_date_list,
                        contract_indicators_dir=self.contract_output_dir

                    )
        total_time = time.time() - start_time
        successful = sum(results_dict.values())

        if logger.isEnabledFor(logging.INFO):
            logger.info(f"[INDICATOR_PROCESSOR] Processing complete | successful={successful}/{len(contract_files)}, time={total_time:.2f}s")
        
        return main_contract
    
    def process_single_contract(self, contract_name: str) -> bool:
        """
        Process a single contract using data_pipeline loader.

        Args:
            contract_name: Name of contract (e.g., 'al2201')

        Returns:
            True if successful, False otherwise
        """
        start_time = time.time()

        # Load contract data using data_pipeline loader
        df = load_contract_ohlcv(
            market=self.market,
            asset=self.asset,
            contract=contract_name
        )

        if df is None or df.empty:
            logger.warning(f"[INDICATOR_PROCESSOR] No data for contract | name={contract_name}")
            return False

        if logger.isEnabledFor(logging.INFO):
            logger.info(f"[INDICATOR_PROCESSOR] Processing contract | name={contract_name}, rows={len(df)}")

        # Preprocess data: for rows with missing open/high/low values, use close price from same row
        if 'close' in df.columns:
            # Fill missing open values with close price from same row
            if 'open' in df.columns:
                df.loc[df['open'].isna(), 'open'] = df.loc[df['open'].isna(), 'close']

            # Fill missing high values with close price from same row
            if 'high' in df.columns:
                df.loc[df['high'].isna(), 'high'] = df.loc[df['high'].isna(), 'close']

            # Fill missing low values with close price from same row
            if 'low' in df.columns:
                df.loc[df['low'].isna(), 'low'] = df.loc[df['low'].isna(), 'close']

        # Convert date column if needed
        if 'date' in df.columns:
            df['date'] = pd.to_datetime(df['date'], format='%Y%m%d')

        # Sort by datetime for intraday data, or by date for daily data
        if 'datetime' in df.columns:
            df = df.sort_values('datetime').reset_index(drop=True)
        elif 'date' in df.columns:
            df = df.sort_values('date').reset_index(drop=True)
        
        # Calculate indicators using rolling window approach
        if self.selected: # if only output strategy indicators
            indicator_results = self._calculate_indicators_for_contract(df)
        else: # output all the indicators in the indicator_dictionary.json
            indicator_results=self._calculate_all_indicators_with_defaults(df)
        
        # Create output dataframe
        output_df = self._create_output_dataframe(df, indicator_results, contract_name)
        
        # Save results
        output_file = self.contract_output_dir / f"{contract_name}_indicators.csv"
        output_df.to_csv(output_file, index=False)
        
        # Also save as pickle for faster loading
        pickle_file = self.contract_output_dir / f"{contract_name}_indicators.pkl"
        output_df.to_pickle(pickle_file)
        
        processing_time = time.time() - start_time
        if logger.isEnabledFor(logging.INFO):
            logger.info(f"[INDICATOR_PROCESSOR] Contract complete | name={contract_name}, time={processing_time:.2f}s, rows={len(output_df)}")
        
        return True
    
    
    def _calculate_indicators_for_contract(self, df: pd.DataFrame) -> Dict[str, np.ndarray]:
        """Calculate indicators for a contract using indicator mapping and utility functions"""
        results = {}

        # Process indicators with lookback periods
        for indicator_name, period_range in self.indicator_config.get('indicators_with_lookback', {}).items():
            # period_range is [start, end], generate all periods in range
            if isinstance(period_range, list) and len(period_range) == 2:
                start_period, end_period = period_range
                for period in range(start_period, end_period + 1):
                    # Calculate indicator for this specific period
                    indicator_result = self._calculate_single_indicator(indicator_name, df, timeperiod=period)

                    # Store result with period-specific name
                    column_name = f"{indicator_name.lower()}_{period}"
                    results[column_name] = indicator_result
            else:
                # Fallback for single values or direct lists
                for period in period_range if isinstance(period_range, list) else [period_range]:
                    indicator_result = self._calculate_single_indicator(indicator_name, df, timeperiod=period)
                    column_name = f"{indicator_name.lower()}_{period}"
                    results[column_name] = indicator_result

        # Process indicators without lookback periods
        for indicator_name in self.indicator_config.get('indicators_without_lookback', []):
            # Calculate indicator without period parameter
            indicator_result = self._calculate_single_indicator(indicator_name, df)

            # Store result with indicator name
            results[indicator_name.lower()] = indicator_result

        # Process indicators with special parameters
        for indicator_name in self.indicator_config.get('indicators_with_special_params', []):
            # Calculate indicator with special parameters (no additional params needed)
            indicator_result = self._calculate_single_indicator(indicator_name, df)

            # Store result with indicator name
            results[indicator_name.lower()] = indicator_result

        # Add context indicators based on frequency
        if self.frequency == "day":
            # Interday: add market_regime for analyzers
            if 'market_regime' not in results:
                if logger.isEnabledFor(logging.INFO):
                    logger.info("[INDICATOR_PROCESSOR] Adding market_regime | reason=required by analyzers")
                market_regime_result = self._calculate_single_indicator('MARKET_REGIME', df)
                results['market_regime'] = market_regime_result
        else:
            # Intraday: add session_phase and volatility_state
            # Check both results dict AND input df to avoid duplicate columns
            if 'session_phase' not in results and 'session_phase' not in df.columns:
                if logger.isEnabledFor(logging.INFO):
                    logger.info("[INDICATOR_PROCESSOR] Adding session_phase | reason=intraday context")
                results['session_phase'] = self._calculate_single_indicator('SESSION_PHASE', df)
            if 'volatility_state' not in results and 'volatility_state' not in df.columns:
                if logger.isEnabledFor(logging.INFO):
                    logger.info("[INDICATOR_PROCESSOR] Adding volatility_state | reason=intraday context")
                results['volatility_state'] = self._calculate_single_indicator('VOLATILITY_STATE', df)

            # Intraday: add mandatory bar count indicators (for accurate timing with holiday schedules)
            mandatory_bar_indicators = self._calculate_mandatory_bar_count_indicators(df)
            for name, values in mandatory_bar_indicators.items():
                if name not in results:
                    results[name] = values

        return results

    def _calculate_single_indicator(self, indicator_name: str, df: pd.DataFrame, **kwargs) -> np.ndarray:
        """Calculate a single indicator using the utility functions and cluster-based parameter handling

        Args:
            indicator_name: Name of the indicator (e.g., 'RSI', 'MACD_LINE')
            df: DataFrame containing OHLCV data
            **kwargs: Additional parameters based on indicator cluster

        Returns:
            np.ndarray: Calculated indicator values
        """
        # Get indicator info from mapping (frequency-aware)
        indicator_info = get_indicator_info(indicator_name.upper(), frequency=self.frequency)

        if not indicator_info:
            raise ValueError(f"No mapping found for indicator: {indicator_name}")

        cluster = indicator_info["cluster"]

        # Get the actual function using the frequency-aware get_function method
        indicator_function = get_function(indicator_name.upper(), frequency=self.frequency)

        if not indicator_function:
            raise ValueError(f"Could not find function for indicator: {indicator_name}")

        # Prepare parameters based on cluster type
        # Use frequency-scaled defaults from self.default_params (set from ctx.get_indicator_params())
        if cluster == "indicators_with_lookback":
            # These indicators require df + timeperiod
            # Use frequency-scaled default from context
            default_period = self.default_params.get('rsi_period')
            timeperiod = kwargs.get('timeperiod', default_period)
            # Pass indicator_name for multi-return functions
            result = indicator_function(df, timeperiod=timeperiod, indicator_name=indicator_name)


        elif cluster == "indicators_without_lookback":
            # These indicators only require df, but some need frequency-specific params
            upper_name = indicator_name.upper()

            if upper_name in ('NIGHT_OR_HIGH', 'NIGHT_OR_LOW', 'DAY_OR_HIGH', 'DAY_OR_LOW', 'OR_BREAKOUT'):
                # Opening range indicators need bar_size_minutes for OR calculation
                result = indicator_function(
                    df,
                    bar_size_minutes=self.bar_size_minutes,
                    indicator_name=indicator_name
                )
            elif upper_name in ('VOLUME_PERCENTILE', 'VOLUME_VS_SESSION_AVG'):
                # Volume indicators need bars_per_day for lookback calculation
                result = indicator_function(
                    df,
                    bars_per_day=self.ctx.bars_per_day,
                    indicator_name=indicator_name
                )
            else:
                # Other indicators without lookback - pass bar_size_minutes if available
                extra_kwargs = {}
                if self.bar_size_minutes and self.frequency == "minute":
                    extra_kwargs['bar_size_minutes'] = self.bar_size_minutes
                result = indicator_function(df, indicator_name=indicator_name, **extra_kwargs)

        elif cluster == "indicators_with_special_params":
            # These indicators require df + special parameters
            # Use frequency-scaled defaults from context
            if indicator_name.upper().startswith('MACD'):
                # MACD variants - use frequency-scaled defaults
                macd_fast = self.default_params.get('macd_fast')
                macd_slow = self.default_params.get('macd_slow')
                macd_signal = self.default_params.get('macd_signal')
                fastperiod = kwargs.get('fastperiod', macd_fast)
                slowperiod = kwargs.get('slowperiod', macd_slow)
                signalperiod = kwargs.get('signalperiod', macd_signal)
                if 'EXT' in indicator_name.upper():
                    # MACDEXT has additional MA type parameters
                    fastmatype = kwargs.get('fastmatype', 0)
                    slowmatype = kwargs.get('slowmatype', 0)
                    signalmatype = kwargs.get('signalmatype', 0)
                    result = indicator_function(df, fastperiod=fastperiod, fastmatype=fastmatype,
                                               slowperiod=slowperiod, slowmatype=slowmatype,
                                               signalperiod=signalperiod, signalmatype=signalmatype, indicator_name=indicator_name)
                elif 'FIX' in indicator_name.upper():
                    # MACDFIX only has signal period
                    result = indicator_function(df, signalperiod=signalperiod, indicator_name=indicator_name)
                else:
                    # Standard MACD
                    result = indicator_function(df, fastperiod=fastperiod, slowperiod=slowperiod, signalperiod=signalperiod, indicator_name=indicator_name)

            elif indicator_name.upper().startswith('STOCH'):
                # Stochastic variants - use frequency-scaled defaults
                default_rsi = self.default_params.get('rsi_period')
                default_fast = max(3, self.default_params.get('mom_period') // 2)  # ~30min
                if 'RSI' in indicator_name.upper():
                    # STOCHRSI
                    timeperiod = kwargs.get('timeperiod', default_rsi)
                    fastk_period = kwargs.get('fastk_period', default_fast)
                    fastd_period = kwargs.get('fastd_period', 3)
                    fastd_matype = kwargs.get('fastd_matype', 0)
                    result = indicator_function(df, timeperiod=timeperiod, fastk_period=fastk_period,
                                              fastd_period=fastd_period, fastd_matype=fastd_matype, indicator_name=indicator_name)
                elif 'F' in indicator_name.upper() and indicator_name.upper().startswith('STOCHF'):
                    # STOCHF
                    fastk_period = kwargs.get('fastk_period', default_fast)
                    fastd_period = kwargs.get('fastd_period', 3)
                    fastd_matype = kwargs.get('fastd_matype', 0)
                    result = indicator_function(df, fastk_period=fastk_period, fastd_period=fastd_period, fastd_matype=fastd_matype, indicator_name=indicator_name)
                else:
                    # Standard STOCH
                    fastk_period = kwargs.get('fastk_period', default_fast)
                    slowk_period = kwargs.get('slowk_period', 3)
                    slowk_matype = kwargs.get('slowk_matype', 0)
                    slowd_period = kwargs.get('slowd_period', 3)
                    slowd_matype = kwargs.get('slowd_matype', 0)
                    result = indicator_function(df, fastk_period=fastk_period, slowk_period=slowk_period,
                                              slowk_matype=slowk_matype, slowd_period=slowd_period, slowd_matype=slowd_matype, indicator_name=indicator_name)

            elif indicator_name.upper().startswith('BBANDS'):
                # Bollinger Bands - use frequency-scaled bb_period
                default_bb = self.default_params.get('bb_period', 20)
                timeperiod = kwargs.get('timeperiod', default_bb)
                nbdevup = kwargs.get('nbdevup', 2)
                nbdevdn = kwargs.get('nbdevdn', 2)
                matype = kwargs.get('matype', 0)
                result = indicator_function(df, timeperiod=timeperiod, nbdevup=nbdevup, nbdevdn=nbdevdn, matype=matype, indicator_name=indicator_name)

            elif indicator_name.upper() in ['STDDEV', 'VAR']:
                # Statistics functions - use frequency-scaled default
                default_period = self.default_params.get('bb_period', 20)
                timeperiod = kwargs.get('timeperiod', default_period)
                nbdev = kwargs.get('nbdev', 1)
                result = indicator_function(df, timeperiod=timeperiod, nbdev=nbdev, indicator_name=indicator_name)

            elif indicator_name.upper().startswith('CDL'):
                # Candlestick patterns with penetration parameter
                penetration = kwargs.get('penetration', 0.3)
                result = indicator_function(df, penetration=penetration, indicator_name=indicator_name)

            elif indicator_name.upper() in ['APO', 'PPO']:
                # Price oscillators - use MACD-like defaults from context
                default_fast = self.default_params.get('macd_fast')
                default_slow = self.default_params.get('macd_slow')
                fastperiod = kwargs.get('fastperiod', default_fast)
                slowperiod = kwargs.get('slowperiod', default_slow)
                matype = kwargs.get('matype', 0)
                result = indicator_function(df, fastperiod=fastperiod, slowperiod=slowperiod, matype=matype, indicator_name=indicator_name)

            elif indicator_name.upper() == 'ULTOSC':
                # Ultimate Oscillator - scale periods based on frequency
                # Default ratios: 7:14:28 (1:2:4)
                base_period = self.default_params.get('mom_period')
                timeperiod1 = kwargs.get('timeperiod1', max(3, base_period // 2))
                timeperiod2 = kwargs.get('timeperiod2', base_period)
                timeperiod3 = kwargs.get('timeperiod3', base_period * 2)
                result = indicator_function(df, timeperiod1=timeperiod1, timeperiod2=timeperiod2, timeperiod3=timeperiod3, indicator_name=indicator_name)

            elif indicator_name.upper() in ['MAMA', 'FAMA']:
                # MESA Adaptive Moving Average
                fastlimit = kwargs.get('fastlimit', 0.5)
                slowlimit = kwargs.get('slowlimit', 0.05)
                result = indicator_function(df, fastlimit=fastlimit, slowlimit=slowlimit, indicator_name=indicator_name)

            elif indicator_name.upper() in ['SAR', 'SAREXT']:
                # Parabolic SAR
                if 'EXT' in indicator_name.upper():
                    # SAREXT has many parameters
                    startvalue = kwargs.get('startvalue', 0)
                    offsetonreverse = kwargs.get('offsetonreverse', 0)
                    accelerationinitlong = kwargs.get('accelerationinitlong', 0.02)
                    accelerationlong = kwargs.get('accelerationlong', 0.02)
                    accelerationmaxlong = kwargs.get('accelerationmaxlong', 0.2)
                    accelerationinitshort = kwargs.get('accelerationinitshort', 0.02)
                    accelerationshort = kwargs.get('accelerationshort', 0.02)
                    accelerationmaxshort = kwargs.get('accelerationmaxshort', 0.2)
                    result = indicator_function(df, startvalue=startvalue, offsetonreverse=offsetonreverse,
                                              accelerationinitlong=accelerationinitlong, accelerationlong=accelerationlong,
                                              accelerationmaxlong=accelerationmaxlong, accelerationinitshort=accelerationinitshort,
                                              accelerationshort=accelerationshort, accelerationmaxshort=accelerationmaxshort, indicator_name=indicator_name)
                else:
                    # Standard SAR
                    acceleration = kwargs.get('acceleration', 0.02)
                    maximum = kwargs.get('maximum', 0.2)
                    result = indicator_function(df, acceleration=acceleration, maximum=maximum, indicator_name=indicator_name)

            elif indicator_name.upper() == 'T3':
                # T3 Moving Average - use frequency-scaled default
                default_period = self.default_params.get('ema_fast')
                timeperiod = kwargs.get('timeperiod', default_period)
                vfactor = kwargs.get('vfactor', 0)
                result = indicator_function(df, timeperiod=timeperiod, vfactor=vfactor, indicator_name=indicator_name)

            elif indicator_name.upper() == 'MAVP':
                # Moving Average with Variable Period - use frequency-scaled default
                default_period = self.default_params.get('sma_mid')
                periods = kwargs.get('periods', np.full(len(df), default_period))
                minperiod = kwargs.get('minperiod', 2)
                maxperiod = kwargs.get('maxperiod', default_period * 2)
                matype = kwargs.get('matype', 0)
                result = indicator_function(df, periods=periods, minperiod=minperiod, maxperiod=maxperiod, matype=matype, indicator_name=indicator_name)

            elif indicator_name.upper() == 'ADOSC':
                # Chaikin A/D Oscillator - use frequency-scaled defaults
                base_period = self.default_params.get('mom_period')
                fastperiod = kwargs.get('fastperiod', max(2, base_period // 4))
                slowperiod = kwargs.get('slowperiod', base_period)
                result = indicator_function(df, fastperiod=fastperiod, slowperiod=slowperiod, indicator_name=indicator_name)

            elif indicator_name.upper() == 'MARKET_REGIME':
                # Market regime classification (v3 with Choppiness Index)
                # Use optimized params from self.regime_params, allow kwargs override
                fast_ma_period = kwargs.get('fast_ma_period', self.regime_params.get('fast_ma_period'))
                slow_ma_period = kwargs.get('slow_ma_period', self.regime_params.get('slow_ma_period'))
                adx_period = kwargs.get('adx_period', self.regime_params.get('adx_period'))
                adx_trend_threshold = kwargs.get('adx_trend_threshold', self.regime_params.get('adx_trend_threshold'))
                atr_period = kwargs.get('atr_period', self.regime_params.get('atr_period'))
                vol_lookback = kwargs.get('vol_lookback', self.regime_params.get('vol_lookback'))
                vol_high_percentile = kwargs.get('vol_high_percentile', self.regime_params.get('vol_high_percentile'))
                chop_period = kwargs.get('chop_period', self.regime_params.get('chop_period'))
                # Handle parameter name difference: interday uses 'chop_threshold', intraday uses 'chop_high_threshold'
                chop_threshold = kwargs.get('chop_threshold', self.regime_params.get('chop_threshold') or self.regime_params.get('chop_high_threshold', 50.0))
                min_regime_bars = kwargs.get('min_regime_bars', self.regime_params.get('min_regime_bars'))

                result = indicator_function(
                    df,
                    fast_ma_period=fast_ma_period,
                    slow_ma_period=slow_ma_period,
                    adx_period=adx_period,
                    adx_trend_threshold=adx_trend_threshold,
                    atr_period=atr_period,
                    vol_lookback=vol_lookback,
                    vol_high_percentile=vol_high_percentile,
                    chop_period=chop_period,
                    chop_threshold=chop_threshold,
                    min_regime_bars=min_regime_bars,
                    indicator_name=indicator_name
                )

            elif indicator_name.upper().startswith('SR_ZONE'):
                # Support/Resistance zone indicators
                lookback_period = kwargs.get('lookback_period', 50)
                zone_tolerance = kwargs.get('zone_tolerance', 0.5)
                min_touches = kwargs.get('min_touches', 3)
                result = indicator_function(df, lookback_period=lookback_period,
                                          zone_tolerance=zone_tolerance,
                                          min_touches=min_touches,
                                          indicator_name=indicator_name)

            else:
                # Default special parameter handling
                result = indicator_function(df, indicator_name=indicator_name, **kwargs)

        elif cluster == "intraday_context_indicators":
            # Intraday context indicators (SESSION_PHASE, VOLATILITY_STATE)
            if indicator_name.upper() == 'SESSION_PHASE':
                # Pass bar_size for correct phase names (granular vs aggregated)
                result = indicator_function(df, indicator_name=indicator_name, bar_size=self.bar_size)
            elif indicator_name.upper() == 'VOLATILITY_STATE':
                atr_period = kwargs.get('atr_period', self.regime_params.get('atr_period', 14))
                vol_lookback = kwargs.get('vol_lookback', self.regime_params.get('vol_lookback', 100))
                high_percentile = kwargs.get('high_percentile', self.regime_params.get('high_percentile', 75.0))
                low_percentile = kwargs.get('low_percentile', self.regime_params.get('low_percentile', 25.0))
                result = indicator_function(
                    df,
                    atr_period=atr_period,
                    vol_lookback=vol_lookback,
                    high_percentile=high_percentile,
                    low_percentile=low_percentile,
                    indicator_name=indicator_name
                )
            elif indicator_name.upper() == 'INTRADAY_CONTEXT':
                result = indicator_function(df, indicator_name=indicator_name)
            else:
                result = indicator_function(df, indicator_name=indicator_name)

        else:
            raise ValueError(f"Unknown cluster type: {cluster}")

        return result

    def _calculate_mandatory_bar_count_indicators(self, df: pd.DataFrame) -> Dict[str, np.ndarray]:
        """
        Calculate mandatory bar count indicators for intraday data.

        These indicators are always generated regardless of indicator configuration,
        as they are essential for accurate timing control (especially with holiday
        schedules where night sessions may be absent).

        Indicators:
        - bar_of_day: Current bar index within trading day (0-indexed)
        - bars_remaining: Bars until end of trading day
        - total_bars_today: Total bars for this trading day (93 or 45)
        - has_night_session: Whether this day has night session (False after holidays)
        - bar_of_session: Current bar index within session (0-indexed)
        - bars_remaining_in_session: Bars until end of current session
        - session_bars_total: Total bars for current session (48/27/18)

        Args:
            df: DataFrame with datetime, trading_date, and session_phase columns

        Returns:
            Dict mapping indicator names to calculated values
        """
        from echolon.indicators.calculators.intraday.indicators import (
            bar_of_day,
            bars_remaining,
            total_bars_today,
            has_night_session,
            bar_of_session,
            bars_remaining_in_session,
            session_bars_total,
        )

        results = {}

        if self.session_availability is None:
            logger.warning("[INDICATOR_PROCESSOR] Session availability not loaded, skipping bar count indicators")
            return results

        if logger.isEnabledFor(logging.INFO):
            logger.info("[INDICATOR_PROCESSOR] Calculating mandatory bar count indicators | reason=intraday timing")

        # bar_of_day doesn't need session_availability
        results['bar_of_day'] = bar_of_day(df)

        # bar_of_session doesn't need session_availability
        results['bar_of_session'] = bar_of_session(df)

        # These require session_availability for accurate counts
        results['bars_remaining'] = bars_remaining(df, session_availability=self.session_availability)
        results['total_bars_today'] = total_bars_today(df, session_availability=self.session_availability)
        results['has_night_session'] = has_night_session(df, session_availability=self.session_availability)
        results['bars_remaining_in_session'] = bars_remaining_in_session(df, session_availability=self.session_availability)
        results['session_bars_total'] = session_bars_total(df, session_availability=self.session_availability)

        return results


    def _load_strategy_indicators(self) -> Dict[str, Any]:
        """
        Load and validate indicator configuration from strategy_indicator_list.json.

        This method uses Pydantic validation to ensure the JSON file has the correct format:
        - indicators_with_lookback: {INDICATOR_NAME: [min_period, max_period]}
        - indicators_without_lookback: [INDICATOR_NAME1, INDICATOR_NAME2, ...]
        - indicators_with_special_params: [INDICATOR_NAME1, INDICATOR_NAME2, ...]

        Raises:
            ValidationError: If the JSON format is invalid
            FileNotFoundError: If the JSON file doesn't exist
        """
        strategy_file = PROJECT_ROOT / "modules" / "quant_engine" / "strategy" / "platform_agnostic" / "strategy_indicator_list.json"

        if logger.isEnabledFor(logging.INFO):
            logger.info(f"[INDICATOR_PROCESSOR] Loading strategy indicators | path={strategy_file}")

        # Validate JSON format using Pydantic
        is_valid, error_msg, validated_model = validate_indicator_list_json(str(strategy_file))

        if not is_valid:
            logger.error("=" * 80)
            logger.error("❌ INDICATOR LIST VALIDATION FAILED")
            logger.error("=" * 80)
            logger.error(f"File: {strategy_file}")
            logger.error(f"Error: {error_msg}")
            logger.error("")
            logger.error("Expected format:")
            logger.error('{')
            logger.error('  "indicators_with_lookback": {')
            logger.error('    "INDICATOR_NAME": [min_period, max_period]')
            logger.error('  },')
            logger.error('  "indicators_without_lookback": ["NAME1", "NAME2"],')
            logger.error('  "indicators_with_special_params": ["NAME1", "NAME2"]')
            logger.error('}')
            logger.error("")
            logger.error("Common issues:")
            logger.error("  1. indicators_with_lookback must have EXACTLY 2 values [min, max]")
            logger.error("  2. Do NOT include extra fields like 'description', 'usage', etc.")
            logger.error("  3. All indicator names must be strings")
            logger.error("  4. No duplicate indicators across categories")
            logger.error("=" * 80)
            raise ValueError(f"Invalid strategy_indicator_list.json format: {error_msg}")

        # Convert Pydantic model back to dict for backward compatibility
        config = {
            "indicators_with_lookback": validated_model.indicators_with_lookback,
            "indicators_without_lookback": validated_model.indicators_without_lookback,
            "indicators_with_special_params": validated_model.indicators_with_special_params
        }

        # Calculate total indicators that will be generated
        total_lookback = sum(
            max_p - min_p + 1
            for min_p, max_p in config['indicators_with_lookback'].values()
        )
        total_no_lookback = len(config['indicators_without_lookback'])
        total_special = len(config['indicators_with_special_params'])
        total = total_lookback + total_no_lookback + total_special

        if logger.isEnabledFor(logging.INFO):
            logger.info("[INDICATOR_PROCESSOR] Validation PASSED ✅")
            logger.info(f"[INDICATOR_PROCESSOR] Lookback indicators | types={len(config['indicators_with_lookback'])}, total={total_lookback}")
            for name, periods in config['indicators_with_lookback'].items():
                min_p, max_p = periods
                count = max_p - min_p + 1
                logger.info(f"[INDICATOR_PROCESSOR]   • {name} | periods={min_p}-{max_p}, count={count}")
            logger.info(f"[INDICATOR_PROCESSOR] No-lookback indicators | count={total_no_lookback}")
            logger.info(f"[INDICATOR_PROCESSOR] Special param indicators | count={total_special}")
            logger.info(f"[INDICATOR_PROCESSOR] Total to generate | count={total}")

        return config


    def _extract_indicator_keys(self) -> List[str]:
        """Extract all indicator keys for processing"""
        keys = []

        # Add indicators with lookback periods
        for indicator_name in self.indicator_config.get('indicators_with_lookback', {}):
            keys.append(indicator_name)

        # Add indicators without lookback periods
        for indicator_name in self.indicator_config.get('indicators_without_lookback', []):
            keys.append(indicator_name)

        # Add indicators with special parameters
        for indicator_name in self.indicator_config.get('indicators_with_special_params', []):
            keys.append(indicator_name)

        if logger.isEnabledFor(logging.INFO):
            logger.info(f"[INDICATOR_PROCESSOR] Extracted indicator keys | count={len(keys)}, keys={keys}")
        return keys
    
    def get_contract_files(self) -> List[str]:
        """Get list of contract files to process using data_pipeline loader."""
        # Use data_pipeline loader to get available contracts
        all_contracts = get_available_contracts(market=self.market, asset=self.asset)

        # Filter for contracts matching our futures code (e.g., "al" for aluminum)
        contract_files = []
        for contract_name in all_contracts:
            # Check if contract name starts with our futures code
            if contract_name.startswith(self.futures_code):
                # Filter for recent contracts (2018+) as per existing system
                if self._is_contract_in_backtest_period(contract_name):
                    contract_files.append(contract_name)

        contract_files.sort()
        if logger.isEnabledFor(logging.INFO):
            logger.info(f"[INDICATOR_PROCESSOR] Contracts found | asset={self.asset}, code={self.futures_code}, count={len(contract_files)}")

        return contract_files
    
    def _is_contract_in_backtest_period(self, contract_name: str) -> bool:
        """Check if contract is within backtest period.

        Uses ``self._backtest_start_year`` (passed at construction time) to
        ensure consistent filtering between indicator calculation and
        backtesting.
        """
        import re

        if self._backtest_start_year is None:
            raise ValueError(
                "backtest_start_year is required for contract filtering. "
                "Pass it to IndicatorProcessor(..., backtest_start_year=YYYY) "
                "or forward it via run_indicator_calculation(start_date=...)."
            )
        backtest_start_year = self._backtest_start_year

        # Use regex to extract year from contract name (e.g., al1803, cu2401)
        # Pattern: letters followed by 4 digits (YYMM)
        match = re.match(r'^([a-zA-Z]+)(\d{4})$', contract_name)
        if not match:
            return False

        try:
            date_part = match.group(2)  # e.g., "1803", "2401"
            year_suffix = int(date_part[:2])  # e.g., 18, 24

            # Convert 2-digit year to full year
            full_year = 2000 + year_suffix

            return full_year >= backtest_start_year

        except (ValueError, IndexError):
            logger.warning(f"[INDICATOR_PROCESSOR] Year parse failed | contract={contract_name}")
            return False
    
    
    def _calculate_all_indicators_with_defaults(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Calculate indicators required by market_metrics analysis module.
        Uses frequency-specific analysis indicator config files:
        - interday: modules/market_metrics/config/interday_analysis_indicators.json
        - intraday: modules/market_metrics/config/intraday_analysis_indicators.json

        Args:
            df: DataFrame containing OHLCV data

        Returns:
            Dict with indicator name -> calculated values
        """

        # Load analysis indicators from market_metrics config (frequency-aware)
        all_indicators = get_analysis_indicator_list(frequency=self.frequency)

        logger.info(f"[INDICATOR_PROCESSOR] Calculating {len(all_indicators)} analysis indicators for {self.frequency}")

        indicator_results = {}

        # Bar count indicators that require session_availability (handled separately)
        MANDATORY_BAR_INDICATORS = {
            'bar_of_day', 'bars_remaining', 'total_bars_today', 'has_night_session',
            'bar_of_session', 'bars_remaining_in_session', 'session_bars_total'
        }

        # Process all indicators using their mapped functions
        for indicator_name in all_indicators:
            # Skip bar count indicators - they're handled by _calculate_mandatory_bar_count_indicators
            if indicator_name.lower() in MANDATORY_BAR_INDICATORS and self.frequency != "day":
                continue

            # Get the function from indicator mapping
            indicator_function = get_function(indicator_name.upper(), frequency=self.frequency)

            if not indicator_function:
                logger.warning(f"[INDICATOR_PROCESSOR] No function mapping | indicator={indicator_name}")
                continue

            # Handle context/regime indicators based on frequency
            if indicator_name.upper() == 'MARKET_REGIME' and self.frequency == "day":
                # Interday: use optimized regime params
                chop_threshold = self.regime_params.get('chop_threshold', 50.0)
                result = indicator_function(
                    df,
                    fast_ma_period=self.regime_params.get('fast_ma_period'),
                    slow_ma_period=self.regime_params.get('slow_ma_period'),
                    adx_period=self.regime_params.get('adx_period'),
                    adx_trend_threshold=self.regime_params.get('adx_trend_threshold'),
                    atr_period=self.regime_params.get('atr_period'),
                    vol_lookback=self.regime_params.get('vol_lookback'),
                    vol_high_percentile=self.regime_params.get('vol_high_percentile'),
                    chop_period=self.regime_params.get('chop_period'),
                    chop_threshold=chop_threshold,
                    min_regime_bars=self.regime_params.get('min_regime_bars'),
                    indicator_name=indicator_name
                )
            elif indicator_name.upper() == 'VOLATILITY_STATE':
                # Intraday volatility state with context params
                result = indicator_function(
                    df,
                    atr_period=self.regime_params.get('atr_period', 14),
                    vol_lookback=self.regime_params.get('vol_lookback', 100),
                    high_percentile=self.regime_params.get('high_percentile', 75.0),
                    low_percentile=self.regime_params.get('low_percentile', 25.0),
                    indicator_name=indicator_name
                )
            elif indicator_name.upper() in ('VOLUME_PERCENTILE', 'VOLUME_VS_SESSION_AVG'):
                # Volume indicators need bars_per_day for lookback calculation
                result = indicator_function(
                    df,
                    bars_per_day=self.ctx.bars_per_day,
                    indicator_name=indicator_name
                )
            elif indicator_name.upper() in ('NIGHT_OR_HIGH', 'NIGHT_OR_LOW', 'DAY_OR_HIGH', 'DAY_OR_LOW', 'OR_BREAKOUT'):
                # Opening range indicators need bar_size_minutes for OR calculation
                result = indicator_function(
                    df,
                    bar_size_minutes=self.ctx.bar_size_minutes,
                    indicator_name=indicator_name
                )
            else:
                # Call function with df and indicator_name
                # The utility functions will use their own default parameters
                result = indicator_function(df, indicator_name=indicator_name)

            # Store result with indicator name as key
            indicator_results[indicator_name.lower()] = result
            logger.debug(f"Calculated {indicator_name}")

        # Add mandatory bar count indicators for intraday
        if self.frequency != "day":
            mandatory_bar_indicators = self._calculate_mandatory_bar_count_indicators(df)
            for name, values in mandatory_bar_indicators.items():
                if name not in indicator_results:
                    indicator_results[name] = values

        return indicator_results

    def _create_output_dataframe(self, original_df: pd.DataFrame,
                               indicator_results: Dict[str, np.ndarray],
                               contract_name: str) -> pd.DataFrame:
        """Create output dataframe with original data and indicators - optimized to avoid fragmentation"""
        # Start with original data (without Unnamed columns)
        unnamed_cols = [col for col in original_df.columns if col.startswith('Unnamed')]
        if unnamed_cols:
            base_df = original_df.drop(columns=unnamed_cols)
            if logger.isEnabledFor(logging.INFO):
                logger.info(f"[INDICATOR_PROCESSOR] Removed Unnamed columns | contract={contract_name}, count={len(unnamed_cols)}")
        else:
            base_df = original_df.copy()

        # Prepare indicator columns that match DataFrame length
        indicator_dfs = []
        for indicator_name, values in indicator_results.items():
            if len(values) == len(base_df):
                indicator_dfs.append(pd.DataFrame({indicator_name: values}))
            else:
                logger.warning(f"[INDICATOR_PROCESSOR] Length mismatch | indicator={indicator_name}, contract={contract_name}")

        # Prepare metadata columns
        metadata_dict = {}

        # Add trading_date if not already present and date column exists
        # Use int64 format (YYYYMMDD) for efficient comparison in extract_main_contract_indicators
        if 'trading_date' not in base_df.columns and 'date' in base_df.columns:
            metadata_dict['trading_date'] = base_df['date'].dt.strftime('%Y%m%d').astype(int)

        # Add contract name if not already present
        if 'contract' not in base_df.columns:
            metadata_dict['contract'] = contract_name

        # Add contract expiry (need temporary df for calculation)
        if len(base_df) > 0:
            temp_df = base_df.copy()
            temp_df['contract'] = contract_name
            metadata_dict['contract_expiry'] = self.get_contract_expiry_date(temp_df)

        metadata_df = pd.DataFrame(metadata_dict, index=base_df.index)

        # Combine all DataFrames at once using concat
        dfs_to_concat = [base_df] + indicator_dfs + [metadata_df]
        output_df = pd.concat(dfs_to_concat, axis=1)

        return output_df
    

    def extract_main_contract_indicators(self,trading_dates_list: List[datetime],
                                    contract_indicators_dir: str) -> pd.DataFrame:
        """
        Extract and stitch together indicators from individual contract files
        based on main contract for each trading date.

        Uses main_contract.csv lookup table for accurate main contract determination.

        Parameters
        ----------
        trading_dates_list : List[datetime]
            List of trading dates
        contract_indicators_dir : str
            Directory containing individual contract indicator files

        Returns
        -------
        pd.DataFrame
            Stitched indicators following main contract progression
        """
        if logger.isEnabledFor(logging.INFO):
            logger.info("[INDICATOR_PROCESSOR] Extracting main contract indicators")

        main_contract_indicators = []

        for trading_date in trading_dates_list:
            # Get main contract for this date using SHFE contract rules
            try:
                main_contract = get_main_contract(trading_date.date(), self.futures_code)
            except ValueError:
                logger.debug(f"No main contract for date: {trading_date}")
                continue

            # Load the contract's indicator file
            contract_file = os.path.join(contract_indicators_dir, f"{main_contract}_indicators.pkl")

            if not os.path.exists(contract_file):
                logger.warning(f"Contract indicator file not found: {contract_file}")
                continue

            contract_data = pd.read_pickle(contract_file)

            # Filter to this specific trading date
            # trading_date column is int64 format (YYYYMMDD), convert for comparison
            trading_date_int = int(trading_date.strftime('%Y%m%d'))
            date_data = contract_data[contract_data['trading_date'] == trading_date_int]

            if not date_data.empty:
                main_contract_indicators.append(date_data)
            else:
                logger.debug(f"No data for {main_contract} on {trading_date_int}")
                

        
        if main_contract_indicators:
            combined_indicators = pd.concat(main_contract_indicators, ignore_index=True)

            # Sort by datetime to ensure chronological order (for intraday data)
            if 'datetime' in combined_indicators.columns:
                combined_indicators = combined_indicators.sort_values('datetime').reset_index(drop=True)
            else:
                combined_indicators = combined_indicators.sort_values('trading_date').reset_index(drop=True)

            # Save to strategy_indicators.csv and .pkl in output directory
            csv_file = os.path.join(self.output_dir, "strategy_indicators.csv")
            pkl_file = os.path.join(self.output_dir, "strategy_indicators.pkl")

            # Set date as index before saving (required by data_loader.py)
            combined_indicators_with_index = combined_indicators.copy()
            combined_indicators_with_index['date'] = pd.to_datetime(combined_indicators_with_index['date'])
            combined_indicators_with_index.set_index('date', inplace=True)

            # Save with date as index
            combined_indicators_with_index.to_csv(csv_file, index=True)
            combined_indicators_with_index.to_pickle(pkl_file)

            # Save indicator metadata
            self.save_strategy_indicator_metadata(combined_indicators)

            if logger.isEnabledFor(logging.INFO):
                logger.info(f"[INDICATOR_PROCESSOR] Main contract indicators extracted | rows={len(combined_indicators)}")
                logger.info(f"[INDICATOR_PROCESSOR] Saved | csv={csv_file}, pkl={pkl_file}")
            return combined_indicators_with_index
        else:
            logger.error("[INDICATOR_PROCESSOR] Extraction failed | reason=No main contract indicators")
            return pd.DataFrame()


    def save_strategy_indicator_metadata(self, combined_indicators: pd.DataFrame) -> None:
        """
        Extract indicator column headers from combined indicators and save metadata.

        Parameters
        ----------
        combined_indicators : pd.DataFrame
            Combined main contract indicators DataFrame
        """
        # Define base columns to exclude (OHLCV, metadata, and market data columns)
        base_columns = [
            'date', 'open', 'high', 'low', 'close', 'volume',
            'prev_close', 'prev_settlement', 'settlement',
            'price_change', 'settlement_change', 'turnover', 'open_interest'
        ]

        # Extract indicator columns (exclude base columns)
        indicator_columns = [col for col in combined_indicators.columns if col not in base_columns]

        # Create metadata dictionary
        metadata = {
            "indicator_columns": indicator_columns
        }

        # Save to JSON file
        metadata_file = os.path.join(self.output_dir, "strategy_indicator_metadata.json")

        with open(metadata_file, 'w') as f:
            json.dump(metadata, f, indent=2)

        if logger.isEnabledFor(logging.INFO):
            logger.info(f"[INDICATOR_PROCESSOR] Metadata saved | indicators={len(indicator_columns)}, path={metadata_file}")

    def get_contract_expiry_date(self, contract_data: pd.DataFrame) -> int:
        """
        Get expiry date for a contract using SHFE contract rules.

        Delegates to get_expiry_date from contract_rules.py for accurate
        calculation using the trading calendar.

        Parameters
        ----------
        contract_data : pd.DataFrame
            Contract OHLCV data with 'contract' column

        Returns
        -------
        int
            Expiry date as integer (YYYYMMDD format)
        """
        if contract_data.empty:
            return 0

        # Get contract name from the data
        contract_name = contract_data['contract'].iloc[0] if 'contract' in contract_data.columns else None

        if not contract_name:
            # Fallback if no contract name
            logger.warning("No contract name found in data, using last date as expiry")
            last_date = contract_data.iloc[-1]['date']
            if isinstance(last_date, str):
                return int(last_date)
            elif isinstance(last_date, (int, float)):
                return int(last_date)
            else:
                return int(last_date.strftime('%Y%m%d'))

        # Use canonical get_expiry_date from contract_rules.py
        # This uses TradingCalendar for accurate last trading day calculation
        expiry_date = get_expiry_date(str(contract_name))

        return int(expiry_date.strftime('%Y%m%d'))


