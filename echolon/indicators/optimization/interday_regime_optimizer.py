"""
Interday Regime Classification Optimizer
=========================================

Optimizes the market_regime classification parameters for DAILY (interday) data
using Optuna to find the most powerful parameter combination for regime detection.

This optimizer supports the 4-state interday regime model:
- trending_up (1): Strong uptrend with clean price action
- trending_down (-1): Strong downtrend with clean price action
- ranging (0): Low trend strength or indeterminate
- volatile (2): Choppy price action + high volatility (whipsaw danger)

Key Optimization Objectives:
1. Return Separation: trending_up should have positive returns, trending_down negative
2. Direction Alignment: Correct directional prediction within regime segments
3. Volatility Coherence: Volatile regime should have highest actual volatility
4. Regime Balance: No single regime should dominate excessively
5. Transition Stability: Regimes should be stable (not flip-flopping)

Usage:
    from echolon.indicators.optimization.interday_regime_optimizer import InterdayRegimeOptimizer

    optimizer = InterdayRegimeOptimizer(data_dir='path/to/contracts')
    best_params, study = optimizer.optimize(n_trials=100)

    # Validate results
    validation_report = optimizer.validate_params(best_params)

See Also:
    - intraday_regime_optimizer.py: For intraday (minute) data with 5-state model
    - modules/indicators/calculators/interday/market_regime.py: The calculator this optimizes
"""

import numpy as np
import pandas as pd
import optuna
from optuna.samplers import TPESampler
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass
from pathlib import Path
import logging
import json
from datetime import datetime

from echolon.config.indicator_config import IndicatorConfig
from echolon.config.markets.factory import MarketFactory
from echolon.config.paths_config import PathsConfig

logger = logging.getLogger(__name__)


@dataclass
class RegimeQualityMetrics:
    """Container for regime classification quality metrics"""

    # Return metrics
    trending_up_return: float = 0.0
    trending_down_return: float = 0.0
    ranging_return: float = 0.0
    volatile_return: float = 0.0
    return_separation: float = 0.0  # abs(up - down)

    # Direction alignment (per-segment cumulative returns)
    segment_up_return: float = 0.0
    segment_down_return: float = 0.0
    direction_alignment_score: float = 0.0  # Correct direction percentage

    # Volatility coherence
    trending_up_vol: float = 0.0
    trending_down_vol: float = 0.0
    ranging_vol: float = 0.0
    volatile_vol: float = 0.0
    volatility_coherence_score: float = 0.0

    # Regime distribution
    trending_up_pct: float = 0.0
    trending_down_pct: float = 0.0
    ranging_pct: float = 0.0
    volatile_pct: float = 0.0
    balance_score: float = 0.0

    # Transition stability
    transition_stability: float = 0.0
    avg_regime_duration: float = 0.0

    # Sample sizes
    n_bars: int = 0
    n_segments: int = 0

    # Composite score
    composite_score: float = 0.0

    def to_dict(self) -> Dict:
        """Convert to dictionary"""
        return {
            'trending_up_return': self.trending_up_return,
            'trending_down_return': self.trending_down_return,
            'ranging_return': self.ranging_return,
            'volatile_return': self.volatile_return,
            'return_separation': self.return_separation,
            'segment_up_return': self.segment_up_return,
            'segment_down_return': self.segment_down_return,
            'direction_alignment_score': self.direction_alignment_score,
            'volatility_coherence_score': self.volatility_coherence_score,
            'trending_up_pct': self.trending_up_pct,
            'trending_down_pct': self.trending_down_pct,
            'ranging_pct': self.ranging_pct,
            'volatile_pct': self.volatile_pct,
            'balance_score': self.balance_score,
            'transition_stability': self.transition_stability,
            'avg_regime_duration': self.avg_regime_duration,
            'n_bars': self.n_bars,
            'n_segments': self.n_segments,
            'composite_score': self.composite_score
        }


@dataclass
class RegimeOptimizerConfig:
    """Configuration for regime optimizer"""

    # Optimization weights (sum to 1.0)
    weight_return_separation: float = 0.25
    weight_direction_alignment: float = 0.30
    weight_volatility_coherence: float = 0.15
    weight_balance: float = 0.15
    weight_stability: float = 0.15

    # Parameter bounds (upper bounds intersected with IndicatorConfig caps at suggest-time)
    fast_ma_period_range: Tuple[int, int] = (10, 40)  # Narrowed to avoid overfitting
    slow_ma_period_range: Tuple[int, int] = (30, 180)  # Minimum 30 to ensure separation from fast
    adx_period_range: Tuple[int, int] = (10, 50)  # Narrowed: 7 is too responsive
    adx_threshold_range: Tuple[float, float] = (18.0, 35.0)  # Raised minimum
    atr_period_range: Tuple[int, int] = (10, 60)
    vol_lookback_range: Tuple[int, int] = (30, 120)
    vol_percentile_range: Tuple[float, float] = (65.0, 85.0)
    min_regime_bars_range: Tuple[int, int] = (3, 10)  # Changed from (1, 10) - no single-bar regimes

    # Choppiness Index parameters (new)
    chop_period_range: Tuple[int, int] = (10, 20)
    chop_threshold_range: Tuple[float, float] = (45.0, 58.0)  # Lowered based on copper futures analysis

    # Hard constraints for regime viability (new)
    # Relaxed slightly to allow optimizer to find viable solutions
    min_volatile_pct: float = 1.0  # Volatile regime must be at least 1%
    min_ranging_pct: float = 5.0   # Ranging regime must be at least 5%
    min_trending_pct: float = 2.0  # Each trending regime must be at least 2% (markets can be range-bound)
    max_single_regime_pct: float = 85.0  # No single regime can exceed 85% (allow range-dominated markets)

    # Validation thresholds
    min_bars_per_regime: int = 30
    min_segments_per_regime: int = 3
    min_return_separation: float = 0.001  # 0.1% daily

    # Optuna settings
    n_trials: int = 100
    n_jobs: int = -1  # Use all available CPUs for parallel optimization
    timeout: Optional[int] = None
    seed: int = 42


class InterdayRegimeOptimizer:
    """
    Optimizes interday (daily) market regime classification parameters using Optuna.

    The optimizer evaluates regime classification quality based on:
    1. Economic validity (return separation between regimes)
    2. Direction alignment (trending regimes capture correct moves)
    3. Volatility coherence (volatile regime has highest volatility)
    4. Regime balance (reasonable distribution)
    5. Transition stability (regimes don't flip-flop)

    This optimizer is designed for DAILY bar data with 4 regime states:
    - trending_up (1), trending_down (-1), ranging (0), volatile (2)

    For intraday (minute) data optimization, use IntradayRegimeOptimizer instead.
    """

    def __init__(self,
                 data_dir: str,
                 config: Optional[RegimeOptimizerConfig] = None,
                 futures: str = "copper",
                 market: str = "SHFE",
                 backtest_start_year: Optional[int] = None,
                 indicator_config: Optional[IndicatorConfig] = None):
        """
        Initialize regime optimizer.

        Parameters
        ----------
        data_dir : str
            Directory containing contract CSV files (sort_by_contract/)
        config : RegimeOptimizerConfig, optional
            Optimizer configuration
        futures : str
            Futures type for contract file pattern (name or code)
        market : str
            Market code (e.g., "SHFE")
        backtest_start_year : int, optional
            Earliest contract year (e.g. 2018) for filtering.  Required when
            contract filtering is desired; pass ``None`` to disable filtering
            (all contracts are loaded).
        indicator_config : IndicatorConfig, optional
            Period caps for technical indicators.  When *None* the default
            :class:`IndicatorConfig` is used.
        """
        self.data_dir = Path(data_dir)
        self.config = config or RegimeOptimizerConfig()
        self.indicator_config = indicator_config or IndicatorConfig()
        self.futures = futures
        self.market = market
        self._backtest_start_year = backtest_start_year

        # Determine futures code using MarketFactory (supports code or name)
        instrument_spec = MarketFactory.get_instrument_flexible(market, futures)
        self.futures_code = instrument_spec.code if instrument_spec else futures.lower()[:2]

        # Load and prepare data
        self.contract_data = self._load_contract_data()

        # Study storage
        self.study: Optional[optuna.Study] = None
        self.best_params: Optional[Dict] = None
        self.optimization_history: List[Dict] = []

    # def _load_contract_data(self) -> List[pd.DataFrame]:
    #     """
    #     Load contract data files for optimization using main_contract.csv.

    #     Uses main_contract.csv to find which contracts were the main contract
    #     during [BACKTEST_START_DATE, BACKTEST_END_DATE] for contract SELECTION.
    #     Loads each selected contract's FULL data (no row-level date filtering)
    #     to preserve indicator lookback warmup and maximize statistical power.
    #     """
    #     from echolon.markets.shfe.contract_rules import _load_main_contract_data
    #     from echolon.config.settings import BACKTEST_END_DATE

    #     backtest_start = pd.Timestamp(BACKTEST_START_DATE).date()
    #     # backtest_start = pd.Timestamp("2019-01-01").date()
    #     backtest_end = pd.Timestamp(BACKTEST_END_DATE).date()

    #     # Load main_contract.csv to find which contracts were active
    #     main_contract_df = _load_main_contract_data(self.futures_code)

    #     # Filter to rows within [backtest_start, backtest_end]
    #     mask = [(d >= backtest_start and d <= backtest_end) for d in main_contract_df['date']]
    #     filtered_mc = main_contract_df[mask]

    #     # Extract unique contract names (e.g., "al2402.SF" -> "al2402")
    #     contract_names = set()
    #     for mc in filtered_mc['main_contract'].unique():
    #         clean_name = mc.split('.')[0] if '.' in mc else mc
    #         contract_names.add(clean_name)

    #     logger.info(f"[REGIME_OPTIMIZER] Backtest period {BACKTEST_START_DATE} to {BACKTEST_END_DATE} | "
    #                  f"main contracts found: {len(contract_names)}")

    #     # Load full contract CSV files (no date filtering on rows)
    #     contract_data = []
    #     for contract_name in sorted(contract_names):
    #         csv_path = self.data_dir / f"{contract_name}.csv"
    #         if not csv_path.exists():
    #             logger.warning(f"[REGIME_OPTIMIZER] Contract file not found: {csv_path}")
    #             continue

    #         df = pd.read_csv(csv_path)

    #         # Preprocess missing OHLC values
    #         if 'close' in df.columns:
    #             if 'open' in df.columns:
    #                 df.loc[df['open'].isna(), 'open'] = df.loc[df['open'].isna(), 'close']
    #             if 'high' in df.columns:
    #                 df.loc[df['high'].isna(), 'high'] = df.loc[df['high'].isna(), 'close']
    #             if 'low' in df.columns:
    #                 df.loc[df['low'].isna(), 'low'] = df.loc[df['low'].isna(), 'close']

    #         df['contract_name'] = contract_name
    #         contract_data.append(df)

    #     logger.info(f"[REGIME_OPTIMIZER] Loaded {len(contract_data)} contracts for optimization")
    #     return contract_data
    def _load_contract_data(self) -> List[pd.DataFrame]:
        """Load all contract data files for optimization"""
        contract_files = sorted(self.data_dir.glob(f"{self.futures_code}*.csv"))

        # Use ``self._backtest_start_year`` for consistent filtering between
        # regime optimization and backtesting.  When unset, all contracts are
        # loaded without filtering.
        backtest_start_year = self._backtest_start_year

        # Filter for contracts within backtest period
        recent_contracts = []
        for f in contract_files:
            contract_name = f.stem
            # Extract year from contract name (e.g., cu2401 -> 24 -> 2024)
            import re
            match = re.match(r'^([a-zA-Z]+)(\d{4})$', contract_name)
            if match:
                year_suffix = int(match.group(2)[:2])
                full_year = 2000 + year_suffix
                if backtest_start_year is None or full_year >= backtest_start_year:
                    recent_contracts.append(f)

        # Load data
        contract_data = []
        for f in recent_contracts:
            df = pd.read_csv(f)
            if len(df) >= 100:  # Only use contracts with sufficient data
                # Preprocess
                if 'close' in df.columns:
                    if 'open' in df.columns:
                        df.loc[df['open'].isna(), 'open'] = df.loc[df['open'].isna(), 'close']
                    if 'high' in df.columns:
                        df.loc[df['high'].isna(), 'high'] = df.loc[df['high'].isna(), 'close']
                    if 'low' in df.columns:
                        df.loc[df['low'].isna(), 'low'] = df.loc[df['low'].isna(), 'close']

                df['contract_name'] = f.stem
                contract_data.append(df)

        logger.info(f"[REGIME_OPTIMIZER] Loaded {len(contract_data)} contracts for optimization")
        return contract_data
    
    def _calculate_regime_with_params(self,
                                       df: pd.DataFrame,
                                       params: Dict) -> np.ndarray:
        """
        Calculate regime classification with given parameters.

        This is a standalone implementation to avoid circular imports
        and allow testing different parameters.

        Uses the new Choppiness Index-based volatile regime detection:
        - Volatile = CHOPPY (high Choppiness Index) + HIGH volatility (high ATR)
        - Trending = Strong ADX + direction confirmed + NOT choppy
        - Ranging = Default for everything else
        """
        import talib

        high = df['high'].values
        low = df['low'].values
        close = df['close'].values
        n = len(close)

        # Extract parameters
        fast_ma_period = params['fast_ma_period']
        slow_ma_period = params['slow_ma_period']
        adx_period = params['adx_period']
        adx_trend_threshold = params['adx_trend_threshold']
        atr_period = params['atr_period']
        vol_lookback = params['vol_lookback']
        vol_high_percentile = params['vol_high_percentile']
        chop_period = params.get('chop_period', 14)
        chop_threshold = params.get('chop_threshold', 61.8)
        min_regime_bars = params['min_regime_bars']

        # Calculate trend indicators
        fast_ma = talib.EMA(close, timeperiod=fast_ma_period)
        slow_ma = talib.EMA(close, timeperiod=slow_ma_period)
        adx = talib.ADX(high, low, close, timeperiod=adx_period)
        plus_di = talib.PLUS_DI(high, low, close, timeperiod=adx_period)
        minus_di = talib.MINUS_DI(high, low, close, timeperiod=adx_period)
        atr = talib.ATR(high, low, close, timeperiod=atr_period)

        # Normalized ATR for volatility detection
        natr = atr / close * 100

        # Rolling percentile for volatility
        vol_percentile = self._rolling_percentile(natr, vol_lookback)

        # Choppiness Index for choppy market detection
        choppiness = self._choppiness_index(high, low, close, chop_period)

        # Condition flags
        strong_trend = adx > adx_trend_threshold
        uptrend = (fast_ma > slow_ma) & (close > slow_ma) & (plus_di > minus_di)
        downtrend = (fast_ma < slow_ma) & (close < slow_ma) & (minus_di > plus_di)
        high_volatility = vol_percentile > vol_high_percentile
        choppy_market = choppiness > chop_threshold

        # Valid mask
        valid_mask = ~(
            np.isnan(adx) | np.isnan(slow_ma) | np.isnan(fast_ma) |
            np.isnan(atr) | np.isnan(vol_percentile) | np.isnan(choppiness)
        )

        # Regime classification with corrected priority order
        regime = np.zeros(n, dtype=np.float64)  # 0 = ranging (default)

        # PRIORITY 1: Volatile - choppy + high volatility (whipsaw danger)
        regime[valid_mask & choppy_market & high_volatility] = 2

        # PRIORITY 2: Trending Up - strong trend + bullish + NOT choppy
        regime[valid_mask & strong_trend & uptrend & ~choppy_market] = 1

        # PRIORITY 3: Trending Down - strong trend + bearish + NOT choppy
        regime[valid_mask & strong_trend & downtrend & ~choppy_market] = -1

        # PRIORITY 4: Ranging - everything else (already default)

        # Apply persistence filter
        if min_regime_bars > 1:
            regime = self._apply_regime_persistence(regime, min_regime_bars)

        return regime

    def _choppiness_index(self, high: np.ndarray, low: np.ndarray,
                          close: np.ndarray, period: int = 14) -> np.ndarray:
        """
        Calculate Choppiness Index (CHOP).

        CHOP = 100 * LOG10(SUM(TR, period) / (HH - LL)) / LOG10(period)

        High values (>61.8) = choppy/consolidating
        Low values (<38.2) = trending
        """
        import talib

        n = len(close)

        # Calculate True Range
        tr = talib.TRANGE(high, low, close)

        # Rolling calculations
        tr_series = pd.Series(tr)
        high_series = pd.Series(high)
        low_series = pd.Series(low)

        sum_tr = tr_series.rolling(window=period).sum().values
        highest_high = high_series.rolling(window=period).max().values
        lowest_low = low_series.rolling(window=period).min().values

        # Calculate range (avoid division by zero)
        price_range = highest_high - lowest_low
        price_range = np.maximum(price_range, 0.0001)

        # Choppiness Index formula
        with np.errstate(divide='ignore', invalid='ignore'):
            chop = 100 * np.log10(sum_tr / price_range) / np.log10(period)

        chop = np.clip(chop, 0, 100)

        return chop

    def _rolling_percentile(self, values: np.ndarray, lookback: int) -> np.ndarray:
        """Calculate rolling percentile"""
        n = len(values)
        result = np.full(n, 50.0, dtype=np.float64)

        for i in range(lookback, n):
            window = values[i - lookback:i]
            valid_window = window[~np.isnan(window)]
            if len(valid_window) > 0 and not np.isnan(values[i]):
                result[i] = np.sum(valid_window <= values[i]) / len(valid_window) * 100

        return result

    def _apply_regime_persistence(self, regime: np.ndarray, min_bars: int) -> np.ndarray:
        """Apply persistence filter to regime"""
        n = len(regime)
        smoothed = regime.copy()

        if n < min_bars:
            return smoothed

        current_regime = regime[0]
        i = 1

        while i < n:
            if regime[i] != current_regime:
                new_regime = regime[i]
                persist_count = 0

                for j in range(i, min(i + min_bars, n)):
                    if regime[j] == new_regime:
                        persist_count += 1
                    else:
                        break

                if persist_count >= min_bars:
                    current_regime = new_regime
                else:
                    for j in range(i, min(i + persist_count, n)):
                        smoothed[j] = current_regime

            i += 1

        return smoothed

    def evaluate_regime_quality(self,
                                params: Dict,
                                return_metrics: bool = False) -> float:
        """
        Evaluate regime classification quality for given parameters.

        Parameters
        ----------
        params : Dict
            Regime classification parameters
        return_metrics : bool
            If True, return (score, metrics) tuple

        Returns
        -------
        float or Tuple[float, RegimeQualityMetrics]
            Composite quality score (higher is better)
        """
        all_concurrent_returns = {-1: [], 0: [], 1: [], 2: []}
        all_realized_vol = {-1: [], 0: [], 1: [], 2: []}
        all_segment_returns = {-1: [], 0: [], 1: [], 2: []}

        total_bars = 0
        total_transitions = 0
        regime_durations = []
        regime_counts = {-1: 0, 0: 0, 1: 0, 2: 0}

        for df in self.contract_data:
            # Calculate regime
            regime = self._calculate_regime_with_params(df, params)

            # Skip if too many NaNs in regime (bad parameters)
            valid_regime = regime[~np.isnan(regime)]
            if len(valid_regime) < 50:
                continue

            # Calculate returns and volatility
            df = df.copy()
            df['regime'] = regime
            df['concurrent_return'] = df['close'].pct_change()
            df['realized_vol'] = df['concurrent_return'].rolling(20).std() * np.sqrt(252)

            # Collect bar-level metrics
            for val in [-1, 0, 1, 2]:
                mask = df['regime'] == val
                regime_counts[val] += mask.sum()
                all_concurrent_returns[val].extend(
                    df.loc[mask, 'concurrent_return'].dropna().tolist()
                )
                all_realized_vol[val].extend(
                    df.loc[mask, 'realized_vol'].dropna().tolist()
                )

            # Calculate segment-level cumulative returns
            df['regime_change'] = (df['regime'] != df['regime'].shift()).cumsum()
            for seg_id in df['regime_change'].unique():
                seg = df[df['regime_change'] == seg_id]
                if len(seg) >= 3:
                    regime_val = seg['regime'].iloc[0]
                    cum_ret = (1 + seg['concurrent_return'].dropna()).prod() - 1
                    all_segment_returns[regime_val].append(cum_ret)
                    regime_durations.append(len(seg))

            # Transition count
            transitions = (regime != np.roll(regime, 1)).sum() - 1
            total_transitions += max(0, transitions)
            total_bars += len(regime)

        # Check minimum data requirements
        min_samples = self.config.min_bars_per_regime
        if (len(all_concurrent_returns[1]) < min_samples or
            len(all_concurrent_returns[-1]) < min_samples):
            if return_metrics:
                return 0.0, RegimeQualityMetrics()
            return 0.0

        # Calculate metrics
        metrics = RegimeQualityMetrics()
        metrics.n_bars = total_bars
        metrics.n_segments = sum(len(v) for v in all_segment_returns.values())

        # 1. Return metrics (concurrent returns)
        metrics.trending_up_return = np.mean(all_concurrent_returns[1]) * 100 if all_concurrent_returns[1] else 0
        metrics.trending_down_return = np.mean(all_concurrent_returns[-1]) * 100 if all_concurrent_returns[-1] else 0
        metrics.ranging_return = np.mean(all_concurrent_returns[0]) * 100 if all_concurrent_returns[0] else 0
        metrics.volatile_return = np.mean(all_concurrent_returns[2]) * 100 if all_concurrent_returns[2] else 0
        metrics.return_separation = abs(metrics.trending_up_return - metrics.trending_down_return)

        # 2. Direction alignment (segment cumulative returns)
        metrics.segment_up_return = np.mean(all_segment_returns[1]) * 100 if all_segment_returns[1] else 0
        metrics.segment_down_return = np.mean(all_segment_returns[-1]) * 100 if all_segment_returns[-1] else 0

        # Direction alignment score: proportion of segments with correct direction
        correct_up = sum(1 for r in all_segment_returns[1] if r > 0)
        correct_down = sum(1 for r in all_segment_returns[-1] if r < 0)
        total_directional = len(all_segment_returns[1]) + len(all_segment_returns[-1])
        metrics.direction_alignment_score = (correct_up + correct_down) / max(1, total_directional)

        # 3. Volatility coherence
        metrics.trending_up_vol = np.mean(all_realized_vol[1]) if all_realized_vol[1] else 0
        metrics.trending_down_vol = np.mean(all_realized_vol[-1]) if all_realized_vol[-1] else 0
        metrics.ranging_vol = np.mean(all_realized_vol[0]) if all_realized_vol[0] else 0
        metrics.volatile_vol = np.mean(all_realized_vol[2]) if all_realized_vol[2] else 0

        # Volatile regime should have highest volatility
        other_vols = [v for v in [metrics.trending_up_vol, metrics.trending_down_vol, metrics.ranging_vol] if v > 0]
        if metrics.volatile_vol > 0 and other_vols:
            metrics.volatility_coherence_score = min(1.0, metrics.volatile_vol / max(other_vols))
        else:
            metrics.volatility_coherence_score = 0.5  # Neutral if no volatile periods

        # 4. Regime balance
        total_count = sum(regime_counts.values())
        max_regime_pct = 0.0
        if total_count > 0:
            metrics.trending_up_pct = regime_counts[1] / total_count * 100
            metrics.trending_down_pct = regime_counts[-1] / total_count * 100
            metrics.ranging_pct = regime_counts[0] / total_count * 100
            metrics.volatile_pct = regime_counts[2] / total_count * 100

            max_regime_pct = max(metrics.trending_up_pct, metrics.trending_down_pct,
                                metrics.ranging_pct, metrics.volatile_pct)

            # Balance score: reward even distribution across regimes
            # Penalize if any regime is too dominant or too rare
            balance_penalty = 0.0
            # Penalize deviation from ideal ranges
            # Ideal: trending 20-35%, ranging 20-40%, volatile 5-15%
            if metrics.volatile_pct < 5.0:
                balance_penalty += (5.0 - metrics.volatile_pct) / 5.0 * 0.2
            elif metrics.volatile_pct > 15.0:
                balance_penalty += (metrics.volatile_pct - 15.0) / 15.0 * 0.1

            metrics.balance_score = max(0, 1 - balance_penalty - (max_regime_pct - 50) / 100)

        # 5. Transition stability
        if total_bars > 0:
            transition_rate = total_transitions / total_bars
            metrics.transition_stability = 1 - transition_rate

        if regime_durations:
            metrics.avg_regime_duration = np.mean(regime_durations)

        # Calculate composite score (before constraint checks so metrics are complete)
        metrics.composite_score = self._calculate_composite_score(metrics)

        # HARD CONSTRAINTS: Reject parameters that eliminate any regime
        # This ensures all 4 regimes are viable
        # Note: Metrics are fully calculated above so they're available even if constraints fail
        cfg = self.config
        if total_count > 0:
            if metrics.volatile_pct < cfg.min_volatile_pct:
                # Volatile regime must exist (at least 1%)
                if return_metrics:
                    return 0.0, metrics
                return 0.0
            if metrics.ranging_pct < cfg.min_ranging_pct:
                # Ranging regime must exist (at least 10%)
                if return_metrics:
                    return 0.0, metrics
                return 0.0
            if metrics.trending_up_pct < cfg.min_trending_pct:
                # Trending up must exist (at least 10%)
                if return_metrics:
                    return 0.0, metrics
                return 0.0
            if metrics.trending_down_pct < cfg.min_trending_pct:
                # Trending down must exist (at least 10%)
                if return_metrics:
                    return 0.0, metrics
                return 0.0

            if max_regime_pct > cfg.max_single_regime_pct:
                # No single regime can dominate (max 70%)
                if return_metrics:
                    return 0.0, metrics
                return 0.0

        if return_metrics:
            return metrics.composite_score, metrics
        return metrics.composite_score

    def _calculate_composite_score(self, metrics: RegimeQualityMetrics) -> float:
        """
        Calculate weighted composite score from individual metrics.

        The scoring function rewards:
        - High return separation between trending regimes
        - Correct direction alignment (up=positive, down=negative)
        - Volatile regime having highest volatility
        - Balanced regime distribution
        - Stable regime transitions
        """
        cfg = self.config

        # Normalize return separation (scale to 0-1)
        # Typical good separation is 0.05-0.2% daily
        return_sep_score = min(1.0, metrics.return_separation / 0.15)

        # Direction alignment is already 0-1
        direction_score = metrics.direction_alignment_score

        # Bonus for correct signs
        sign_bonus = 0.0
        if metrics.segment_up_return > 0:
            sign_bonus += 0.5
        if metrics.segment_down_return < 0:
            sign_bonus += 0.5
        direction_score = 0.7 * direction_score + 0.3 * sign_bonus

        # Volatility coherence is already 0-1
        vol_score = metrics.volatility_coherence_score

        # Balance score is already 0-1
        balance_score = metrics.balance_score

        # Stability score
        # Penalize if transitions are too frequent OR too rare
        # Ideal: avg duration 5-20 bars
        if metrics.avg_regime_duration > 0:
            if 5 <= metrics.avg_regime_duration <= 20:
                stability_score = metrics.transition_stability
            elif metrics.avg_regime_duration < 5:
                # Too short - penalize
                stability_score = metrics.transition_stability * (metrics.avg_regime_duration / 5)
            else:
                # Too long - slight penalty
                stability_score = metrics.transition_stability * min(1.0, 20 / metrics.avg_regime_duration)
        else:
            stability_score = 0.0

        # Weighted combination
        composite = (
            cfg.weight_return_separation * return_sep_score +
            cfg.weight_direction_alignment * direction_score +
            cfg.weight_volatility_coherence * vol_score +
            cfg.weight_balance * balance_score +
            cfg.weight_stability * stability_score
        )

        return composite

    def _objective(self, trial: optuna.Trial) -> float:
        """Optuna objective function"""
        import os
        import threading

        # Log trial start with process/thread info for parallel monitoring
        pid = os.getpid()
        tid = threading.current_thread().name
        logger.info(f"[REGIME_OPTIMIZER] Trial {trial.number} STARTED | pid={pid}, thread={tid}")

        cfg = self.config

        # Sample parameters with constraints
        fast_ma_period = trial.suggest_int(
            'fast_ma_period',
            cfg.fast_ma_period_range[0],
            cfg.fast_ma_period_range[1]
        )

        # Slow MA must be > fast MA
        slow_ma_min = max(cfg.slow_ma_period_range[0], fast_ma_period + 10)
        slow_ma_period = trial.suggest_int(
            'slow_ma_period',
            slow_ma_min,
            cfg.slow_ma_period_range[1]
        )

        adx_period = trial.suggest_int(
            'adx_period',
            cfg.adx_period_range[0],
            min(cfg.adx_period_range[1], self.indicator_config.get_interday_cap('adx'))
        )

        adx_trend_threshold = trial.suggest_float(
            'adx_trend_threshold',
            cfg.adx_threshold_range[0],
            cfg.adx_threshold_range[1]
        )

        atr_period = trial.suggest_int(
            'atr_period',
            cfg.atr_period_range[0],
            min(cfg.atr_period_range[1], self.indicator_config.get_interday_cap('atr'))
        )

        vol_lookback = trial.suggest_int(
            'vol_lookback',
            cfg.vol_lookback_range[0],
            cfg.vol_lookback_range[1]
        )

        vol_high_percentile = trial.suggest_float(
            'vol_high_percentile',
            cfg.vol_percentile_range[0],
            cfg.vol_percentile_range[1]
        )

        min_regime_bars = trial.suggest_int(
            'min_regime_bars',
            cfg.min_regime_bars_range[0],
            cfg.min_regime_bars_range[1]
        )

        # Choppiness Index parameters (new)
        chop_period = trial.suggest_int(
            'chop_period',
            cfg.chop_period_range[0],
            cfg.chop_period_range[1]
        )

        chop_threshold = trial.suggest_float(
            'chop_threshold',
            cfg.chop_threshold_range[0],
            cfg.chop_threshold_range[1]
        )

        params = {
            'fast_ma_period': fast_ma_period,
            'slow_ma_period': slow_ma_period,
            'adx_period': adx_period,
            'adx_trend_threshold': adx_trend_threshold,
            'atr_period': atr_period,
            'vol_lookback': vol_lookback,
            'vol_high_percentile': vol_high_percentile,
            'chop_period': chop_period,
            'chop_threshold': chop_threshold,
            'min_regime_bars': min_regime_bars
        }

        # Evaluate
        score = self.evaluate_regime_quality(params)

        # Store in history
        self.optimization_history.append({
            'trial': trial.number,
            'params': params.copy(),
            'score': score
        })

        # Log trial completion
        logger.info(f"[REGIME_OPTIMIZER] Trial {trial.number} COMPLETED | score={score:.4f}, pid={pid}, thread={tid}")

        return score

    def optimize(self,
                 n_trials: Optional[int] = None,
                 n_jobs: Optional[int] = None,
                 show_progress: bool = True) -> Tuple[Dict, optuna.Study]:
        """
        Run optimization to find best regime parameters.

        Parameters
        ----------
        n_trials : int, optional
            Number of optimization trials
        n_jobs : int, optional
            Number of parallel jobs
        show_progress : bool
            Whether to show progress bar

        Returns
        -------
        Tuple[Dict, optuna.Study]
            Best parameters and Optuna study object
        """
        import os

        n_trials = n_trials or self.config.n_trials
        n_jobs = n_jobs or self.config.n_jobs

        # Resolve n_jobs=-1 to actual CPU count
        if n_jobs == -1:
            n_jobs = os.cpu_count() or 1

        # Create study
        sampler = TPESampler(seed=self.config.seed)
        self.study = optuna.create_study(
            direction='maximize',
            sampler=sampler,
            study_name='regime_optimization'
        )

        # Optimize
        logger.info(f"[REGIME_OPTIMIZER] Starting optimization | trials={n_trials}, n_jobs={n_jobs}, cpu_count={os.cpu_count()}")

        optuna.logging.set_verbosity(
            optuna.logging.INFO if show_progress else optuna.logging.WARNING
        )

        self.study.optimize(
            self._objective,
            n_trials=n_trials,
            n_jobs=n_jobs,
            timeout=self.config.timeout,
            show_progress_bar=show_progress
        )

        # Extract best parameters
        self.best_params = self.study.best_params

        logger.info(f"[REGIME_OPTIMIZER] Optimization complete | best_score={self.study.best_value:.4f}")
        logger.info(f"[REGIME_OPTIMIZER] Best parameters: {self.best_params}")

        return self.best_params, self.study

    def validate_params(self, params: Dict) -> Dict:
        """
        Comprehensive validation of regime parameters.

        Returns detailed metrics and validation report.
        """
        score, metrics = self.evaluate_regime_quality(params, return_metrics=True)

        validation_report = {
            'score': score,
            'metrics': metrics.to_dict(),
            'params': params,
            'validation_passed': True,
            'warnings': [],
            'recommendations': []
        }

        # Check validation criteria
        if metrics.return_separation < self.config.min_return_separation:
            validation_report['warnings'].append(
                f"Low return separation: {metrics.return_separation:.4f}% "
                f"(threshold: {self.config.min_return_separation:.4f}%)"
            )

        if metrics.segment_up_return <= 0:
            validation_report['warnings'].append(
                f"Trending up segments have non-positive returns: {metrics.segment_up_return:.4f}%"
            )
            validation_report['validation_passed'] = False

        if metrics.segment_down_return >= 0:
            validation_report['warnings'].append(
                f"Trending down segments have non-negative returns: {metrics.segment_down_return:.4f}%"
            )
            validation_report['validation_passed'] = False

        if metrics.direction_alignment_score < 0.55:
            validation_report['warnings'].append(
                f"Low direction alignment: {metrics.direction_alignment_score:.2%}"
            )

        if metrics.ranging_pct > 70:
            validation_report['warnings'].append(
                f"Ranging regime too dominant: {metrics.ranging_pct:.1f}%"
            )
            validation_report['recommendations'].append(
                "Consider lowering adx_trend_threshold to capture more trends"
            )

        if metrics.avg_regime_duration < 3:
            validation_report['warnings'].append(
                f"Regime duration too short: {metrics.avg_regime_duration:.1f} bars"
            )
            validation_report['recommendations'].append(
                "Consider increasing min_regime_bars"
            )

        return validation_report

    def save_results(self, output_path: str):
        """Save optimization results to file"""
        results = {
            'timestamp': datetime.now().isoformat(),
            'best_params': self.best_params,
            'best_score': self.study.best_value if self.study else None,
            'n_trials': len(self.optimization_history),
            'config': {
                'weight_return_separation': self.config.weight_return_separation,
                'weight_direction_alignment': self.config.weight_direction_alignment,
                'weight_volatility_coherence': self.config.weight_volatility_coherence,
                'weight_balance': self.config.weight_balance,
                'weight_stability': self.config.weight_stability,
            },
            'validation': self.validate_params(self.best_params) if self.best_params else None,
            'top_10_trials': sorted(
                self.optimization_history,
                key=lambda x: x['score'],
                reverse=True
            )[:10]
        }

        with open(output_path, 'w') as f:
            json.dump(results, f, indent=2, default=str)

        logger.info(f"[REGIME_OPTIMIZER] Results saved to {output_path}")

    def get_default_params(self) -> Dict:
        """Get current default parameters from market_regime.py"""
        return {
            'fast_ma_period': 20,
            'slow_ma_period': 50,
            'adx_period': 14,
            'adx_trend_threshold': 20.0,
            'atr_period': 14,
            'vol_lookback': 60,
            'vol_high_percentile': 75.0,
            'chop_period': 14,
            'chop_threshold': 50.0,  # Lowered from 61.8 based on copper futures analysis
            'min_regime_bars': 3
        }

    def compare_with_default(self) -> Dict:
        """Compare optimized parameters with default parameters"""
        default_params = self.get_default_params()

        default_score, default_metrics = self.evaluate_regime_quality(
            default_params, return_metrics=True
        )

        if self.best_params:
            optimized_score, optimized_metrics = self.evaluate_regime_quality(
                self.best_params, return_metrics=True
            )
        else:
            optimized_score, optimized_metrics = 0.0, RegimeQualityMetrics()

        comparison = {
            'default': {
                'params': default_params,
                'score': default_score,
                'metrics': default_metrics.to_dict()
            },
            'optimized': {
                'params': self.best_params,
                'score': optimized_score,
                'metrics': optimized_metrics.to_dict()
            },
            'improvement': {
                'score_delta': optimized_score - default_score,
                'score_pct_improvement': (optimized_score - default_score) / max(0.001, default_score) * 100,
                'return_separation_delta': (
                    optimized_metrics.return_separation - default_metrics.return_separation
                ),
                'direction_alignment_delta': (
                    optimized_metrics.direction_alignment_score -
                    default_metrics.direction_alignment_score
                )
            }
        }

        return comparison


# =============================================================================
# Public module-level helper
# =============================================================================

def optimize_regime_params(
    ctx,
    data_dir: Optional[str] = None,
    n_trials: int = 400,
    config: Optional[RegimeOptimizerConfig] = None,
    backtest_start_year: Optional[int] = None,
    indicator_config: Optional[IndicatorConfig] = None,
    paths: Optional[PathsConfig] = None,
) -> Dict:
    """Run regime-classifier hyperparameter optimization and return the winning dict.

    Convenience wrapper around :class:`InterdayRegimeOptimizer` that accepts a
    :class:`~echolon.config.markets.core.context.TradingContext` and resolves
    market/instrument details automatically.  The caller should prefer this
    function over constructing :class:`InterdayRegimeOptimizer` directly so
    that future API changes are absorbed here.

    Args:
        ctx: TradingContext (interday daily bars expected).  Provides
            ``market_code``, ``instrument_name``, and ``is_interday``.
        data_dir: Directory containing contract CSV files
            (``sort_by_contract/``).  When *None* the standard workspace path
            ``{paths.market_data_dir}/{market}/{instrument}/sort_by_contract``
            is used.  If both ``data_dir`` and ``paths`` are supplied,
            ``data_dir`` wins.
        n_trials: Number of Optuna trials.  Defaults to 400 (same as the
            historical implicit default).
        config: Optional :class:`RegimeOptimizerConfig` to override
            search bounds and weights.  When *None* a default config is built
            with ``n_trials`` applied.
        backtest_start_year: Earliest contract year to include (e.g. 2018).
            Pass *None* to load all available contracts.
        indicator_config: Optional :class:`IndicatorConfig` to override
            indicator period caps.  When *None* defaults are used.
        paths: Optional :class:`~echolon.config.paths_config.PathsConfig`
            supplying library-owned directory layout.  Used to derive the
            default ``data_dir`` when the caller does not pass one.  When
            *None* a PathsConfig is built from ``PROJECT_ROOT``.

    Returns:
        dict mapping regime-param names to optimized values.  Shape is
        identical to the ``regime_params`` kwarg accepted by
        ``run_indicator_calculation``.

    Raises:
        ValueError: if ``ctx`` is not interday (regime optimization is
            daily-bar-only; intraday uses session-phase + volatility_state).
    """
    if not ctx.is_interday:
        raise ValueError(
            f"optimize_regime_params requires an interday ctx; "
            f"got frequency={ctx.frequency!r}"
        )

    if data_dir is None:
        if paths is None:
            from echolon.config.settings import PROJECT_ROOT
            paths = PathsConfig.from_project_root(PROJECT_ROOT)
        data_dir = str(
            paths.market_data_dir / ctx.market_code / ctx.instrument_name / "sort_by_contract"
        )

    if config is None:
        config = RegimeOptimizerConfig(n_trials=n_trials)

    optimizer = InterdayRegimeOptimizer(
        data_dir=data_dir,
        config=config,
        futures=ctx.instrument_name,
        market=ctx.market_code,
        backtest_start_year=backtest_start_year,
        indicator_config=indicator_config,
    )

    # optimize() returns Tuple[Dict, optuna.Study]; we return only the params dict
    best_params, _study = optimizer.optimize(n_trials=n_trials)
    return best_params
