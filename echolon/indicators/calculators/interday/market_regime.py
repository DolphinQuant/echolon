import pandas as pd
import numpy as np
import talib
import logging

# Get logger for this module
logger = logging.getLogger(__name__)


# Canonical regime mapping from numeric to string
REGIME_NUMERIC_TO_STRING = {
    1: 'trending_up',
    1.0: 'trending_up',
    -1: 'trending_down',
    -1.0: 'trending_down',
    0: 'ranging',
    0.0: 'ranging',
    2: 'volatile',
    2.0: 'volatile'
}

# Inverse mapping from string to numeric (for backtrader compatibility)
REGIME_STRING_TO_NUMERIC = {
    'trending_up': 1,
    'trending_down': -1,
    'ranging': 0,
    'volatile': 2
}

# String to string mapping for normalization (handles different string formats)
REGIME_STRING_NORMALIZATION = {
    'trending up': 'trending_up',
    'trending down': 'trending_down',
    'trending_up': 'trending_up',
    'trending_down': 'trending_down',
    'ranging': 'ranging',
    'volatile': 'volatile',
    'unknown': 'unknown',
    'mixed': 'mixed',
    'trending': 'trending',  # General trending without direction
    # Handle string numeric values
    '1': 'trending_up',
    '1.0': 'trending_up',
    '-1': 'trending_down',
    '-1.0': 'trending_down',
    '0': 'ranging',
    '0.0': 'ranging',
    '2': 'volatile',
    '2.0': 'volatile',

}

def market_regime(df: pd.DataFrame,
                  # Trend detection parameters
                  fast_ma_period: int = 20,
                  slow_ma_period: int = 50,
                  adx_period: int = 14,
                  adx_trend_threshold: float = 20.0,
                  # Volatility detection parameters
                  atr_period: int = 14,
                  vol_lookback: int = 60,
                  vol_high_percentile: float = 75.0,
                  # Choppiness detection parameters
                  chop_period: int = 14,
                  chop_threshold: float = 50.0,  # Lowered from 61.8 based on copper futures analysis
                  # Smoothing parameters
                  min_regime_bars: int = 3,
                  indicator_name: str = None) -> np.ndarray:
    """
    Calculate market regime based on trend strength, volatility, and choppiness.

    This implementation uses three independent metrics:
    1. ADX for trend STRENGTH (high ADX = strong directional movement)
    2. ATR percentile for VOLATILITY (high ATR = large price swings)
    3. Choppiness Index for CHOPPINESS (high CHOP = messy/whipsaw price action)

    Key insight: High volatility (ATR) often coincides with strong trends (ADX).
    To properly detect "volatile/choppy" markets, we use Choppiness Index which
    measures how "messy" price action is, independent of move magnitude.

    Regime Classification (in priority order):
    - 2:  'volatile'      - CHOPPY price action + HIGH volatility (whipsaw danger)
    - 1:  'trending_up'   - Strong uptrend (ADX > threshold, bullish, NOT choppy)
    - -1: 'trending_down' - Strong downtrend (ADX > threshold, bearish, NOT choppy)
    - 0:  'ranging'       - Default: low trend strength or normal conditions

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame containing OHLCV data with columns: high, low, close
    fast_ma_period : int
        Period for fast EMA (default: 20)
    slow_ma_period : int
        Period for slow EMA (default: 50)
    adx_period : int
        Period for ADX and DI calculation (default: 14)
    adx_trend_threshold : float
        ADX threshold for trend detection (default: 20)
    atr_period : int
        Period for ATR calculation (default: 14)
    vol_lookback : int
        Lookback window for volatility percentile calculation (default: 60)
    vol_high_percentile : float
        Percentile threshold for high volatility detection (default: 75)
    chop_period : int
        Period for Choppiness Index calculation (default: 14)
    chop_threshold : float
        Choppiness Index threshold for choppy market detection (default: 61.8)
        Values > 61.8 indicate consolidation/choppiness
        Values < 38.2 indicate strong trending
    min_regime_bars : int
        Minimum bars for regime persistence filter (default: 3)
    indicator_name : str
        Optional indicator name for logging

    Returns
    -------
    np.ndarray
        Market regime classification as numeric values (1, -1, 0, 2)
    """
    high = df['high'].values
    low = df['low'].values
    close = df['close'].values
    n = len(close)

    # ===== TREND DETECTION (ADX-based) =====
    # Use dual EMA for trend direction
    fast_ma = talib.EMA(close, timeperiod=fast_ma_period)
    slow_ma = talib.EMA(close, timeperiod=slow_ma_period)

    # ADX for trend strength (no upper limit - high ADX = strong trend)
    adx = talib.ADX(high, low, close, timeperiod=adx_period)
    plus_di = talib.PLUS_DI(high, low, close, timeperiod=adx_period)
    minus_di = talib.MINUS_DI(high, low, close, timeperiod=adx_period)

    # Trend strength condition
    strong_trend = adx > adx_trend_threshold

    # Direction confirmation (multiple factors for robustness)
    uptrend = (
        (fast_ma > slow_ma) &       # MA alignment bullish
        (close > slow_ma) &          # Price above slow MA
        (plus_di > minus_di)         # Bullish directional movement
    )
    downtrend = (
        (fast_ma < slow_ma) &        # MA alignment bearish
        (close < slow_ma) &           # Price below slow MA
        (minus_di > plus_di)          # Bearish directional movement
    )

    # ===== VOLATILITY DETECTION (ATR-based) =====
    atr = talib.ATR(high, low, close, timeperiod=atr_period)
    natr = atr / close * 100  # Normalized ATR as percentage

    # Rolling percentile for adaptive volatility threshold
    vol_percentile = _rolling_percentile(natr, vol_lookback)
    high_volatility = vol_percentile > vol_high_percentile

    # ===== CHOPPINESS DETECTION (Choppiness Index) =====
    # Choppiness Index measures how "messy" price action is
    # High values (>61.8) = consolidation/choppy, Low values (<38.2) = trending
    # This is INDEPENDENT of volatility magnitude (ATR)
    choppiness = _choppiness_index(high, low, close, chop_period)
    choppy_market = choppiness > chop_threshold

    # ===== REGIME CLASSIFICATION (with corrected priority) =====
    valid_mask = ~(
        np.isnan(adx) |
        np.isnan(slow_ma) |
        np.isnan(fast_ma) |
        np.isnan(atr) |
        np.isnan(vol_percentile) |
        np.isnan(choppiness)
    )

    # Initialize with ranging (0) as default
    regime = np.full(n, REGIME_STRING_TO_NUMERIC['ranging'], dtype=np.float64)

    # PRIORITY 1: Volatile regime - CHOPPY price action + HIGH volatility
    # This catches whipsaw conditions where trading is dangerous
    # Must be checked FIRST because choppy+volatile periods may also have high ADX
    volatile_mask = valid_mask & choppy_market & high_volatility
    regime[volatile_mask] = REGIME_STRING_TO_NUMERIC['volatile']

    # PRIORITY 2: Trending Up - Strong trend + bullish + NOT choppy
    # Only classify as trending if price action is clean (not choppy)
    trending_up_mask = valid_mask & strong_trend & uptrend & ~choppy_market
    regime[trending_up_mask] = REGIME_STRING_TO_NUMERIC['trending_up']

    # PRIORITY 3: Trending Down - Strong trend + bearish + NOT choppy
    trending_down_mask = valid_mask & strong_trend & downtrend & ~choppy_market
    regime[trending_down_mask] = REGIME_STRING_TO_NUMERIC['trending_down']

    # PRIORITY 4: Ranging - Default for everything else
    # (low trend strength, or normal volatility, or indeterminate direction)
    # Already set as default, no action needed

    # ===== REGIME SMOOTHING =====
    # Apply persistence filter to reduce regime flipping noise
    if min_regime_bars > 1:
        regime = _apply_regime_persistence(regime, min_regime_bars)

    return regime


def _choppiness_index(high: np.ndarray, low: np.ndarray, close: np.ndarray,
                      period: int = 14) -> np.ndarray:
    """
    Calculate Choppiness Index (CHOP).

    The Choppiness Index measures the degree of price consolidation vs trending.
    It's designed to be INDEPENDENT of volatility magnitude.

    Formula: CHOP = 100 * LOG10(SUM(ATR, period) / (Highest High - Lowest Low)) / LOG10(period)

    Interpretation:
    - Values > 61.8: Market is choppy/consolidating (whipsaw risk)
    - Values < 38.2: Market is trending (cleaner moves)
    - Values 38.2-61.8: Neutral/transitional

    Parameters
    ----------
    high : np.ndarray
        High prices
    low : np.ndarray
        Low prices
    close : np.ndarray
        Close prices
    period : int
        Lookback period (default: 14)

    Returns
    -------
    np.ndarray
        Choppiness Index values (0-100 scale)
    """
    n = len(close)
    chop = np.full(n, np.nan, dtype=np.float64)

    # Calculate True Range for each bar
    tr = talib.TRANGE(high, low, close)

    # Convert to pandas for rolling calculations
    tr_series = pd.Series(tr)
    high_series = pd.Series(high)
    low_series = pd.Series(low)

    # Sum of True Range over period
    sum_tr = tr_series.rolling(window=period).sum().values

    # Highest high and lowest low over period
    highest_high = high_series.rolling(window=period).max().values
    lowest_low = low_series.rolling(window=period).min().values

    # Calculate range (avoid division by zero)
    price_range = highest_high - lowest_low
    price_range = np.maximum(price_range, 0.0001)

    # Choppiness Index formula
    # CHOP = 100 * LOG10(SUM(TR, period) / (HH - LL)) / LOG10(period)
    with np.errstate(divide='ignore', invalid='ignore'):
        chop = 100 * np.log10(sum_tr / price_range) / np.log10(period)

    # Clip to valid range (0-100)
    chop = np.clip(chop, 0, 100)

    return chop


def _rolling_percentile(values: np.ndarray, lookback: int) -> np.ndarray:
    """
    Calculate rolling percentile rank of current value within lookback window.

    Parameters
    ----------
    values : np.ndarray
        Input values array
    lookback : int
        Lookback window size

    Returns
    -------
    np.ndarray
        Percentile rank (0-100) of each value within its lookback window
    """
    n = len(values)
    result = np.full(n, 50.0, dtype=np.float64)  # Default to median

    for i in range(lookback, n):
        window = values[i - lookback:i]
        valid_window = window[~np.isnan(window)]

        if len(valid_window) > 0 and not np.isnan(values[i]):
            current = values[i]
            result[i] = np.sum(valid_window <= current) / len(valid_window) * 100

    return result


def _apply_regime_persistence(regime: np.ndarray, min_bars: int) -> np.ndarray:
    """
    Smooth regime transitions by requiring persistence.

    Only confirm a regime change if the new regime persists for at least
    min_bars consecutive periods. This reduces whipsaw at regime boundaries.

    Parameters
    ----------
    regime : np.ndarray
        Raw regime classification array
    min_bars : int
        Minimum consecutive bars required to confirm regime change

    Returns
    -------
    np.ndarray
        Smoothed regime array with persistence filter applied
    """
    n = len(regime)
    smoothed = regime.copy()

    if n < min_bars:
        return smoothed

    current_regime = regime[0]
    i = 1

    while i < n:
        if regime[i] != current_regime:
            # Potential regime change - check persistence
            new_regime = regime[i]
            persist_count = 0

            # Count consecutive bars of new regime
            for j in range(i, min(i + min_bars, n)):
                if regime[j] == new_regime:
                    persist_count += 1
                else:
                    break

            if persist_count >= min_bars:
                # Confirmed regime change
                current_regime = new_regime
            else:
                # Not enough persistence - revert to previous regime
                for j in range(i, min(i + persist_count, n)):
                    smoothed[j] = current_regime

        i += 1

    return smoothed




def convert_regime_to_string(regime_value):
    """
    Convert regime value to standardized string format.
    
    This function handles:
    - Numeric values (1, -1, 0, 2 and their float equivalents)
    - String values (both normalized and non-normalized)
    - NaN/None values (returns 'unknown')
    
    Parameters
    ----------
    regime_value : int, float, str, or None
        Regime value to convert
        
    Returns
    -------
    str
        Standardized regime string ('trending_up', 'trending_down', 'ranging', 'volatile', 'unknown')
    """
    # Handle NaN/None values
    if pd.isna(regime_value) or regime_value is None:
        return 'unknown'
    
    # Handle numeric values (int, float, numpy types)
    if isinstance(regime_value, (int, float, np.integer, np.floating)) and not pd.isna(regime_value):
        # Convert numpy types to standard Python types for consistent lookup
        if isinstance(regime_value, np.integer):
            regime_value = int(regime_value)
        elif isinstance(regime_value, np.floating):
            regime_value = float(regime_value)
        return REGIME_NUMERIC_TO_STRING.get(regime_value, 'unknown')
    
    # Handle string values
    if isinstance(regime_value, str):
        # First try direct lookup
        if regime_value in REGIME_STRING_NORMALIZATION:
            return REGIME_STRING_NORMALIZATION[regime_value]
        
        # Try case-insensitive lookup
        regime_value_lower = regime_value.lower()
        if regime_value_lower in REGIME_STRING_NORMALIZATION:
            return REGIME_STRING_NORMALIZATION[regime_value_lower]
        
        # If it's already a valid regime string, return as is
        if regime_value_lower in ['trending_up', 'trending_down', 'ranging', 'volatile', 'unknown']:
            return regime_value_lower
    
    # If nothing matches, return unknown
    logger.warning(f"[MARKET_REGIME] Unknown value | regime_value={regime_value}, type={type(regime_value)}, returning=unknown")
    return 'unknown'

def convert_regime_to_numeric(regime_value):
    """
    Convert regime value to numeric format for backtrader compatibility.
    
    Parameters
    ----------
    regime_value : str, int, float, or None
        Regime value to convert
        
    Returns
    -------
    int
        Numeric regime value (1, -1, 0, 2) or 0 for unknown
    """
    # First convert to standardized string
    regime_string = convert_regime_to_string(regime_value)
    
    # Then convert to numeric
    return REGIME_STRING_TO_NUMERIC.get(regime_string, 0)  # Default to 0 (ranging) for unknown