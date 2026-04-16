"""
Intraday Indicator Mapping Registry
===================================

Maps indicator names to their calculation functions for intraday data.
Intraday indicators include:
- Session-aware indicators (VWAP, opening range, session levels)
- Time-based features (bar of day, session phase)
- TA-Lib indicators with intraday-calibrated periods
- Two-layer context system:
  - SESSION_PHASE: Time-based session classification (PRIMARY)
  - VOLATILITY_STATE: ATR-based volatility level (SECONDARY)

NOTE: Trend-based regime (trending_up/down) does NOT work for intraday due to
mean-reversion dynamics. Use SESSION_PHASE + VOLATILITY_STATE instead.
"""

# File name mappings for intraday calculators
INDICATOR_FILES = {
    "talib_indicator": "ta_lib",
    "market_context": "market_context",
    "session_indicators": "indicators",
}

# Intraday-specific indicator mapping
# Maps indicator key to function name, cluster, and file
# All functions use intraday-calibrated default periods
INTRADAY_INDICATOR_MAPPING = {
    # =========================================================================
    # SECTION 1: INDICATORS WITH LOOKBACK PERIOD
    # =========================================================================

    # Volatility Indicators
    "ATR": {"function": "atr", "cluster": "indicators_with_lookback", "file": INDICATOR_FILES["talib_indicator"]},
    "NATR": {"function": "natr", "cluster": "indicators_with_lookback", "file": INDICATOR_FILES["talib_indicator"]},

    # Momentum Indicators
    "ADX": {"function": "adx", "cluster": "indicators_with_lookback", "file": INDICATOR_FILES["talib_indicator"]},
    "ADXR": {"function": "adxr", "cluster": "indicators_with_lookback", "file": INDICATOR_FILES["talib_indicator"]},
    "AROON_DOWN": {"function": "aroon", "cluster": "indicators_with_lookback", "file": INDICATOR_FILES["talib_indicator"]},
    "AROON_UP": {"function": "aroon", "cluster": "indicators_with_lookback", "file": INDICATOR_FILES["talib_indicator"]},
    "AROONOSC": {"function": "aroonosc", "cluster": "indicators_with_lookback", "file": INDICATOR_FILES["talib_indicator"]},
    "CCI": {"function": "cci", "cluster": "indicators_with_lookback", "file": INDICATOR_FILES["talib_indicator"]},
    "CMO": {"function": "cmo", "cluster": "indicators_with_lookback", "file": INDICATOR_FILES["talib_indicator"]},
    "DX": {"function": "dx", "cluster": "indicators_with_lookback", "file": INDICATOR_FILES["talib_indicator"]},
    "MFI": {"function": "mfi", "cluster": "indicators_with_lookback", "file": INDICATOR_FILES["talib_indicator"]},
    "MINUS_DI": {"function": "minus_di", "cluster": "indicators_with_lookback", "file": INDICATOR_FILES["talib_indicator"]},
    "MINUS_DM": {"function": "minus_dm", "cluster": "indicators_with_lookback", "file": INDICATOR_FILES["talib_indicator"]},
    "MOM": {"function": "mom", "cluster": "indicators_with_lookback", "file": INDICATOR_FILES["talib_indicator"]},
    "PLUS_DI": {"function": "plus_di", "cluster": "indicators_with_lookback", "file": INDICATOR_FILES["talib_indicator"]},
    "PLUS_DM": {"function": "plus_dm", "cluster": "indicators_with_lookback", "file": INDICATOR_FILES["talib_indicator"]},
    "ROC": {"function": "roc", "cluster": "indicators_with_lookback", "file": INDICATOR_FILES["talib_indicator"]},
    "ROCP": {"function": "rocp", "cluster": "indicators_with_lookback", "file": INDICATOR_FILES["talib_indicator"]},
    "ROCR": {"function": "rocr", "cluster": "indicators_with_lookback", "file": INDICATOR_FILES["talib_indicator"]},
    "ROCR100": {"function": "rocr100", "cluster": "indicators_with_lookback", "file": INDICATOR_FILES["talib_indicator"]},
    "RSI": {"function": "rsi", "cluster": "indicators_with_lookback", "file": INDICATOR_FILES["talib_indicator"]},
    "TRIX": {"function": "trix", "cluster": "indicators_with_lookback", "file": INDICATOR_FILES["talib_indicator"]},
    "WILLR": {"function": "willr", "cluster": "indicators_with_lookback", "file": INDICATOR_FILES["talib_indicator"]},

    # Overlap Studies (Moving Averages)
    "DEMA": {"function": "dema", "cluster": "indicators_with_lookback", "file": INDICATOR_FILES["talib_indicator"]},
    "EMA": {"function": "ema", "cluster": "indicators_with_lookback", "file": INDICATOR_FILES["talib_indicator"]},
    "KAMA": {"function": "kama", "cluster": "indicators_with_lookback", "file": INDICATOR_FILES["talib_indicator"]},
    "MA": {"function": "ma", "cluster": "indicators_with_lookback", "file": INDICATOR_FILES["talib_indicator"]},
    "MIDPOINT": {"function": "midpoint", "cluster": "indicators_with_lookback", "file": INDICATOR_FILES["talib_indicator"]},
    "MIDPRICE": {"function": "midprice", "cluster": "indicators_with_lookback", "file": INDICATOR_FILES["talib_indicator"]},
    "SMA": {"function": "sma", "cluster": "indicators_with_lookback", "file": INDICATOR_FILES["talib_indicator"]},
    "TEMA": {"function": "tema", "cluster": "indicators_with_lookback", "file": INDICATOR_FILES["talib_indicator"]},
    "TRIMA": {"function": "trima", "cluster": "indicators_with_lookback", "file": INDICATOR_FILES["talib_indicator"]},
    "WMA": {"function": "wma", "cluster": "indicators_with_lookback", "file": INDICATOR_FILES["talib_indicator"]},

    # Math Operators
    "MAX": {"function": "max_func", "cluster": "indicators_with_lookback", "file": INDICATOR_FILES["talib_indicator"]},
    "MAXINDEX": {"function": "maxindex", "cluster": "indicators_with_lookback", "file": INDICATOR_FILES["talib_indicator"]},
    "MIN": {"function": "min_func", "cluster": "indicators_with_lookback", "file": INDICATOR_FILES["talib_indicator"]},
    "MININDEX": {"function": "minindex", "cluster": "indicators_with_lookback", "file": INDICATOR_FILES["talib_indicator"]},
    "MINMAX_MIN": {"function": "minmax", "cluster": "indicators_with_lookback", "file": INDICATOR_FILES["talib_indicator"]},
    "MINMAX_MAX": {"function": "minmax", "cluster": "indicators_with_lookback", "file": INDICATOR_FILES["talib_indicator"]},
    "MINMAXINDEX_MIN": {"function": "minmaxindex", "cluster": "indicators_with_lookback", "file": INDICATOR_FILES["talib_indicator"]},
    "MINMAXINDEX_MAX": {"function": "minmaxindex", "cluster": "indicators_with_lookback", "file": INDICATOR_FILES["talib_indicator"]},
    "SUM": {"function": "sum_func", "cluster": "indicators_with_lookback", "file": INDICATOR_FILES["talib_indicator"]},
    "HIGHEST_HIGH": {"function": "max_func", "cluster": "indicators_with_lookback", "file": INDICATOR_FILES["talib_indicator"]},
    "LOWEST_LOW": {"function": "min_func", "cluster": "indicators_with_lookback", "file": INDICATOR_FILES["talib_indicator"]},

    # Statistic Functions
    "BETA": {"function": "beta", "cluster": "indicators_with_lookback", "file": INDICATOR_FILES["talib_indicator"]},
    "CORREL": {"function": "correl", "cluster": "indicators_with_lookback", "file": INDICATOR_FILES["talib_indicator"]},
    "LINEARREG": {"function": "linearreg", "cluster": "indicators_with_lookback", "file": INDICATOR_FILES["talib_indicator"]},
    "LINEARREG_ANGLE": {"function": "linearreg_angle", "cluster": "indicators_with_lookback", "file": INDICATOR_FILES["talib_indicator"]},
    "LINEARREG_INTERCEPT": {"function": "linearreg_intercept", "cluster": "indicators_with_lookback", "file": INDICATOR_FILES["talib_indicator"]},
    "LINEARREG_SLOPE": {"function": "linearreg_slope", "cluster": "indicators_with_lookback", "file": INDICATOR_FILES["talib_indicator"]},
    "TSF": {"function": "tsf", "cluster": "indicators_with_lookback", "file": INDICATOR_FILES["talib_indicator"]},

    # =========================================================================
    # SECTION 2: INDICATORS WITHOUT LOOKBACK PERIOD
    # =========================================================================
    "BOP": {"function": "bop", "cluster": "indicators_without_lookback", "file": INDICATOR_FILES["talib_indicator"]},
    "ADD": {"function": "add", "cluster": "indicators_without_lookback", "file": INDICATOR_FILES["talib_indicator"]},
    "DIV": {"function": "div", "cluster": "indicators_without_lookback", "file": INDICATOR_FILES["talib_indicator"]},
    "MULT": {"function": "mult", "cluster": "indicators_without_lookback", "file": INDICATOR_FILES["talib_indicator"]},
    "SUB": {"function": "sub", "cluster": "indicators_without_lookback", "file": INDICATOR_FILES["talib_indicator"]},
    "ACOS": {"function": "acos", "cluster": "indicators_without_lookback", "file": INDICATOR_FILES["talib_indicator"]},
    "ASIN": {"function": "asin", "cluster": "indicators_without_lookback", "file": INDICATOR_FILES["talib_indicator"]},
    "ATAN": {"function": "atan", "cluster": "indicators_without_lookback", "file": INDICATOR_FILES["talib_indicator"]},
    "CEIL": {"function": "ceil", "cluster": "indicators_without_lookback", "file": INDICATOR_FILES["talib_indicator"]},
    "COS": {"function": "cos", "cluster": "indicators_without_lookback", "file": INDICATOR_FILES["talib_indicator"]},
    "FLOOR": {"function": "floor", "cluster": "indicators_without_lookback", "file": INDICATOR_FILES["talib_indicator"]},
    "LN": {"function": "ln", "cluster": "indicators_without_lookback", "file": INDICATOR_FILES["talib_indicator"]},
    "LOG10": {"function": "log10", "cluster": "indicators_without_lookback", "file": INDICATOR_FILES["talib_indicator"]},
    "SIN": {"function": "sin", "cluster": "indicators_without_lookback", "file": INDICATOR_FILES["talib_indicator"]},
    "SQRT": {"function": "sqrt", "cluster": "indicators_without_lookback", "file": INDICATOR_FILES["talib_indicator"]},
    "TAN": {"function": "tan", "cluster": "indicators_without_lookback", "file": INDICATOR_FILES["talib_indicator"]},
    "TANH": {"function": "tanh", "cluster": "indicators_without_lookback", "file": INDICATOR_FILES["talib_indicator"]},
    "AVGPRICE": {"function": "avgprice", "cluster": "indicators_without_lookback", "file": INDICATOR_FILES["talib_indicator"]},
    "MEDPRICE": {"function": "medprice", "cluster": "indicators_without_lookback", "file": INDICATOR_FILES["talib_indicator"]},
    "TYPPRICE": {"function": "typprice", "cluster": "indicators_without_lookback", "file": INDICATOR_FILES["talib_indicator"]},
    "WCLPRICE": {"function": "wclprice", "cluster": "indicators_without_lookback", "file": INDICATOR_FILES["talib_indicator"]},
    "TRANGE": {"function": "trange", "cluster": "indicators_without_lookback", "file": INDICATOR_FILES["talib_indicator"]},
    "AD": {"function": "ad", "cluster": "indicators_without_lookback", "file": INDICATOR_FILES["talib_indicator"]},
    "OBV": {"function": "obv", "cluster": "indicators_without_lookback", "file": INDICATOR_FILES["talib_indicator"]},

    # Cycle Indicators
    "HT_DCPERIOD": {"function": "ht_dcperiod", "cluster": "indicators_without_lookback", "file": INDICATOR_FILES["talib_indicator"]},
    "HT_DCPHASE": {"function": "ht_dcphase", "cluster": "indicators_without_lookback", "file": INDICATOR_FILES["talib_indicator"]},
    "HT_PHASOR_INPHASE": {"function": "ht_phasor", "cluster": "indicators_without_lookback", "file": INDICATOR_FILES["talib_indicator"]},
    "HT_PHASOR_QUADRATURE": {"function": "ht_phasor", "cluster": "indicators_without_lookback", "file": INDICATOR_FILES["talib_indicator"]},
    "HT_SINE": {"function": "ht_sine", "cluster": "indicators_without_lookback", "file": INDICATOR_FILES["talib_indicator"]},
    "HT_LEADSINE": {"function": "ht_sine", "cluster": "indicators_without_lookback", "file": INDICATOR_FILES["talib_indicator"]},
    "HT_TRENDMODE": {"function": "ht_trendmode", "cluster": "indicators_without_lookback", "file": INDICATOR_FILES["talib_indicator"]},
    "HT_TRENDLINE": {"function": "ht_trendline", "cluster": "indicators_without_lookback", "file": INDICATOR_FILES["talib_indicator"]},

    # Candlestick Patterns (selection)
    "CDL2CROWS": {"function": "cdl2crows", "cluster": "indicators_without_lookback", "file": INDICATOR_FILES["talib_indicator"]},
    "CDL3BLACKCROWS": {"function": "cdl3blackcrows", "cluster": "indicators_without_lookback", "file": INDICATOR_FILES["talib_indicator"]},
    "CDL3INSIDE": {"function": "cdl3inside", "cluster": "indicators_without_lookback", "file": INDICATOR_FILES["talib_indicator"]},
    "CDL3OUTSIDE": {"function": "cdl3outside", "cluster": "indicators_without_lookback", "file": INDICATOR_FILES["talib_indicator"]},
    "CDL3WHITESOLDIERS": {"function": "cdl3whitesoldiers", "cluster": "indicators_without_lookback", "file": INDICATOR_FILES["talib_indicator"]},
    "CDLDOJI": {"function": "cdldoji", "cluster": "indicators_without_lookback", "file": INDICATOR_FILES["talib_indicator"]},
    "CDLENGULFING": {"function": "cdlengulfing", "cluster": "indicators_without_lookback", "file": INDICATOR_FILES["talib_indicator"]},
    "CDLHAMMER": {"function": "cdlhammer", "cluster": "indicators_without_lookback", "file": INDICATOR_FILES["talib_indicator"]},
    "CDLHARAMI": {"function": "cdlharami", "cluster": "indicators_without_lookback", "file": INDICATOR_FILES["talib_indicator"]},
    "CDLMARUBOZU": {"function": "cdlmarubozu", "cluster": "indicators_without_lookback", "file": INDICATOR_FILES["talib_indicator"]},
    "CDLSHOOTINGSTAR": {"function": "cdlshootingstar", "cluster": "indicators_without_lookback", "file": INDICATOR_FILES["talib_indicator"]},

    # =========================================================================
    # SECTION 3: INDICATORS WITH SPECIAL PARAMETERS
    # =========================================================================
    "APO": {"function": "apo", "cluster": "indicators_with_special_params", "file": INDICATOR_FILES["talib_indicator"]},
    "PPO": {"function": "ppo", "cluster": "indicators_with_special_params", "file": INDICATOR_FILES["talib_indicator"]},
    "MACD_LINE": {"function": "macd", "cluster": "indicators_with_special_params", "file": INDICATOR_FILES["talib_indicator"]},
    "MACD_SIGNAL": {"function": "macd", "cluster": "indicators_with_special_params", "file": INDICATOR_FILES["talib_indicator"]},
    "MACD_HISTOGRAM": {"function": "macd", "cluster": "indicators_with_special_params", "file": INDICATOR_FILES["talib_indicator"]},
    "MACDEXT_LINE": {"function": "macdext", "cluster": "indicators_with_special_params", "file": INDICATOR_FILES["talib_indicator"]},
    "MACDEXT_SIGNAL": {"function": "macdext", "cluster": "indicators_with_special_params", "file": INDICATOR_FILES["talib_indicator"]},
    "MACDEXT_HISTOGRAM": {"function": "macdext", "cluster": "indicators_with_special_params", "file": INDICATOR_FILES["talib_indicator"]},
    "MACDFIX_LINE": {"function": "macdfix", "cluster": "indicators_with_special_params", "file": INDICATOR_FILES["talib_indicator"]},
    "MACDFIX_SIGNAL": {"function": "macdfix", "cluster": "indicators_with_special_params", "file": INDICATOR_FILES["talib_indicator"]},
    "MACDFIX_HISTOGRAM": {"function": "macdfix", "cluster": "indicators_with_special_params", "file": INDICATOR_FILES["talib_indicator"]},
    "ULTOSC": {"function": "ultosc", "cluster": "indicators_with_special_params", "file": INDICATOR_FILES["talib_indicator"]},
    "STOCH_SLOWK": {"function": "stoch", "cluster": "indicators_with_special_params", "file": INDICATOR_FILES["talib_indicator"]},
    "STOCH_SLOWD": {"function": "stoch", "cluster": "indicators_with_special_params", "file": INDICATOR_FILES["talib_indicator"]},
    "STOCHF_FASTK": {"function": "stochf", "cluster": "indicators_with_special_params", "file": INDICATOR_FILES["talib_indicator"]},
    "STOCHF_FASTD": {"function": "stochf", "cluster": "indicators_with_special_params", "file": INDICATOR_FILES["talib_indicator"]},
    "STOCHRSI_FASTK": {"function": "stochrsi", "cluster": "indicators_with_special_params", "file": INDICATOR_FILES["talib_indicator"]},
    "STOCHRSI_FASTD": {"function": "stochrsi", "cluster": "indicators_with_special_params", "file": INDICATOR_FILES["talib_indicator"]},
    "BBANDS_UPPER": {"function": "bbands", "cluster": "indicators_with_special_params", "file": INDICATOR_FILES["talib_indicator"]},
    "BBANDS_MIDDLE": {"function": "bbands", "cluster": "indicators_with_special_params", "file": INDICATOR_FILES["talib_indicator"]},
    "BBANDS_LOWER": {"function": "bbands", "cluster": "indicators_with_special_params", "file": INDICATOR_FILES["talib_indicator"]},
    "MAMA": {"function": "mama", "cluster": "indicators_with_special_params", "file": INDICATOR_FILES["talib_indicator"]},
    "FAMA": {"function": "mama", "cluster": "indicators_with_special_params", "file": INDICATOR_FILES["talib_indicator"]},
    "MAVP": {"function": "mavp", "cluster": "indicators_with_special_params", "file": INDICATOR_FILES["talib_indicator"]},
    "SAR": {"function": "sar", "cluster": "indicators_with_special_params", "file": INDICATOR_FILES["talib_indicator"]},
    "SAREXT": {"function": "sarext", "cluster": "indicators_with_special_params", "file": INDICATOR_FILES["talib_indicator"]},
    "T3": {"function": "t3", "cluster": "indicators_with_special_params", "file": INDICATOR_FILES["talib_indicator"]},
    "STDDEV": {"function": "stddev", "cluster": "indicators_with_special_params", "file": INDICATOR_FILES["talib_indicator"]},
    "VAR": {"function": "var", "cluster": "indicators_with_special_params", "file": INDICATOR_FILES["talib_indicator"]},
    "ADOSC": {"function": "adosc", "cluster": "indicators_with_special_params", "file": INDICATOR_FILES["talib_indicator"]},

    # Market Regime - REMOVED (use MARKET_REGIME in indicators_with_special_params cluster instead)

    # =========================================================================
    # SECTION 4: INTRADAY-SPECIFIC INDICATORS
    # =========================================================================

    # Session Indicators - Individual Wrappers (for market_metrics analysis)
    # NOTE: These use indicators_without_lookback as they are computed per-bar without lookback
    "VWAP": {"function": "vwap", "cluster": "indicators_without_lookback", "file": INDICATOR_FILES["session_indicators"]},
    "VWAP_DISTANCE_PCT": {"function": "vwap_distance_pct", "cluster": "indicators_without_lookback", "file": INDICATOR_FILES["session_indicators"]},
    "SESSION_HIGH": {"function": "session_high", "cluster": "indicators_without_lookback", "file": INDICATOR_FILES["session_indicators"]},
    "SESSION_LOW": {"function": "session_low", "cluster": "indicators_without_lookback", "file": INDICATOR_FILES["session_indicators"]},
    "SESSION_POSITION_PCT": {"function": "session_position_pct", "cluster": "indicators_without_lookback", "file": INDICATOR_FILES["session_indicators"]},
    "VOLUME_PERCENTILE": {"function": "volume_percentile", "cluster": "indicators_without_lookback", "file": INDICATOR_FILES["session_indicators"]},
    "VOLUME_VS_SESSION_AVG": {"function": "volume_vs_session_avg", "cluster": "indicators_without_lookback", "file": INDICATOR_FILES["session_indicators"]},

    # Opening Range Indicators
    "NIGHT_OR_HIGH": {"function": "night_or_high", "cluster": "indicators_without_lookback", "file": INDICATOR_FILES["session_indicators"]},
    "NIGHT_OR_LOW": {"function": "night_or_low", "cluster": "indicators_without_lookback", "file": INDICATOR_FILES["session_indicators"]},
    "DAY_OR_HIGH": {"function": "day_or_high", "cluster": "indicators_without_lookback", "file": INDICATOR_FILES["session_indicators"]},
    "DAY_OR_LOW": {"function": "day_or_low", "cluster": "indicators_without_lookback", "file": INDICATOR_FILES["session_indicators"]},
    "OR_BREAKOUT": {"function": "or_breakout", "cluster": "indicators_without_lookback", "file": INDICATOR_FILES["session_indicators"]},

    # Time Features
    "BAR_OF_DAY": {"function": "bar_of_day", "cluster": "indicators_without_lookback", "file": INDICATOR_FILES["session_indicators"]},
    "BARS_REMAINING": {"function": "bars_remaining", "cluster": "indicators_without_lookback", "file": INDICATOR_FILES["session_indicators"]},
    "TOTAL_BARS_TODAY": {"function": "total_bars_today", "cluster": "indicators_without_lookback", "file": INDICATOR_FILES["session_indicators"]},
    "HAS_NIGHT_SESSION": {"function": "has_night_session", "cluster": "indicators_without_lookback", "file": INDICATOR_FILES["session_indicators"]},
    "BAR_OF_SESSION": {"function": "bar_of_session", "cluster": "indicators_without_lookback", "file": INDICATOR_FILES["session_indicators"]},
    "BARS_REMAINING_IN_SESSION": {"function": "bars_remaining_in_session", "cluster": "indicators_without_lookback", "file": INDICATOR_FILES["session_indicators"]},
    "SESSION_BARS_TOTAL": {"function": "session_bars_total", "cluster": "indicators_without_lookback", "file": INDICATOR_FILES["session_indicators"]},
    "HOUR_OF_DAY": {"function": "hour_of_day", "cluster": "indicators_without_lookback", "file": INDICATOR_FILES["session_indicators"]},
    "MINUTE_OF_HOUR": {"function": "minute_of_hour", "cluster": "indicators_without_lookback", "file": INDICATOR_FILES["session_indicators"]},

    # Bulk calculators (legacy - for full DataFrame calculation)
    "SESSION_LEVELS": {"function": "calculate_session_levels", "cluster": "indicators_without_lookback", "file": INDICATOR_FILES["session_indicators"]},
    "OPENING_RANGE": {"function": "calculate_opening_range", "cluster": "indicators_without_lookback", "file": INDICATOR_FILES["session_indicators"]},
    "TIME_FEATURES": {"function": "calculate_time_features", "cluster": "indicators_without_lookback", "file": INDICATOR_FILES["session_indicators"]},

    # Previous Session Indicators
    "PREV_SESSION_HIGH": {"function": "prev_session_high", "cluster": "indicators_without_lookback", "file": INDICATOR_FILES["session_indicators"]},
    "PREV_SESSION_LOW": {"function": "prev_session_low", "cluster": "indicators_without_lookback", "file": INDICATOR_FILES["session_indicators"]},
    "PREV_SESSION_CLOSE": {"function": "prev_session_close", "cluster": "indicators_without_lookback", "file": INDICATOR_FILES["session_indicators"]},
    "GAP_PCT": {"function": "gap_pct", "cluster": "indicators_without_lookback", "file": INDICATOR_FILES["session_indicators"]},

    # Pivot Point Indicators
    "PIVOT": {"function": "pivot", "cluster": "indicators_without_lookback", "file": INDICATOR_FILES["session_indicators"]},
    "PIVOT_R1": {"function": "pivot_r1", "cluster": "indicators_without_lookback", "file": INDICATOR_FILES["session_indicators"]},
    "PIVOT_S1": {"function": "pivot_s1", "cluster": "indicators_without_lookback", "file": INDICATOR_FILES["session_indicators"]},
    "PIVOT_DISTANCE_PCT": {"function": "pivot_distance_pct", "cluster": "indicators_without_lookback", "file": INDICATOR_FILES["session_indicators"]},

    # Normalization Indicators (Tier 2 - High IC Potential)
    "BBANDS_PCT_B": {"function": "bbands_pct_b", "cluster": "indicators_with_special_params", "file": INDICATOR_FILES["session_indicators"]},
    "BBANDS_BANDWIDTH": {"function": "bbands_bandwidth", "cluster": "indicators_with_special_params", "file": INDICATOR_FILES["session_indicators"]},
    "PRICE_ZSCORE": {"function": "price_zscore", "cluster": "indicators_with_special_params", "file": INDICATOR_FILES["session_indicators"]},
    "VWAP_ZSCORE": {"function": "vwap_zscore", "cluster": "indicators_without_lookback", "file": INDICATOR_FILES["session_indicators"]},

    # Keltner Channel Indicators
    "KC_UPPER": {"function": "kc_upper", "cluster": "indicators_with_special_params", "file": INDICATOR_FILES["session_indicators"]},
    "KC_LOWER": {"function": "kc_lower", "cluster": "indicators_with_special_params", "file": INDICATOR_FILES["session_indicators"]},
    "KC_PCT_B": {"function": "kc_pct_b", "cluster": "indicators_with_special_params", "file": INDICATOR_FILES["session_indicators"]},

    # Chaikin Money Flow
    "CMF": {"function": "cmf", "cluster": "indicators_with_special_params", "file": INDICATOR_FILES["session_indicators"]},

    # =========================================================================
    # SECTION 5: INTRADAY CONTEXT INDICATORS (Two-Layer System)
    # =========================================================================

    # Layer 1: SESSION_PHASE - Time-based, deterministic (PRIMARY)
    # Controls WHEN to trade and which strategy to apply
    "SESSION_PHASE": {"function": "session_phase", "cluster": "intraday_context_indicators", "file": INDICATOR_FILES["market_context"]},

    # Layer 2: VOLATILITY_STATE - ATR-based, adaptive (SECONDARY)
    # Controls position sizing and stop distances
    # Values: 0=low, 1=normal, 2=high
    "VOLATILITY_STATE": {"function": "volatility_state", "cluster": "intraday_context_indicators", "file": INDICATOR_FILES["market_context"]},

    # Combined context calculator (returns DataFrame with all context columns)
    "INTRADAY_CONTEXT": {"function": "calculate_intraday_context", "cluster": "intraday_context_indicators", "file": INDICATOR_FILES["market_context"]},
}

# =========================================================================
# Frequency-Scaled Default Parameters
# =========================================================================

def get_intraday_default_params(ctx=None) -> dict:
    """
    Get frequency-scaled default parameters for intraday indicators.

    If ctx (TradingContext) is provided, parameters are scaled to maintain
    consistent lookback periods in real time across different bar sizes.

    Args:
        ctx: TradingContext (if None, falls back to 5m/93 bar defaults)

    Returns:
        Dictionary of indicator parameters
    """
    # Use TradingContext's frequency-scaled parameters
    return ctx.get_indicator_params()


def get_indicator_info(indicator_key: str):
    """Get indicator info by key for intraday."""
    return INTRADAY_INDICATOR_MAPPING.get(indicator_key.upper())


def get_function(indicator_key: str):
    """
    Get the calculator function for an intraday indicator.

    Parameters
    ----------
    indicator_key : str
        Indicator name (e.g., 'RSI', 'VWAP', 'MARKET_REGIME')

    Returns
    -------
    callable
        Function from the appropriate intraday calculator module
    """
    import importlib

    mapping = INTRADAY_INDICATOR_MAPPING.get(indicator_key.upper())
    if not mapping:
        return None

    function_name = mapping["function"]
    file_name = mapping.get("file", INDICATOR_FILES["talib_indicator"])

    # All intraday calculators are in the intraday subdirectory
    module = importlib.import_module(
        f"modules.indicators.calculators.intraday.{file_name}"
    )

    return getattr(module, function_name, None)


def get_cluster_name(indicator_key: str):
    """Get cluster name by indicator key for intraday."""
    mapping = INTRADAY_INDICATOR_MAPPING.get(indicator_key.upper())
    return mapping["cluster"] if mapping else None


def get_indicators_by_cluster(cluster_name: str):
    """Get list of indicators in a specific cluster for intraday."""
    return [key for key, value in INTRADAY_INDICATOR_MAPPING.items()
            if value["cluster"] == cluster_name]


def get_all_clusters():
    """Return list of all intraday indicator clusters."""
    return list(set(value["cluster"] for value in INTRADAY_INDICATOR_MAPPING.values()))


def indicator_exists(indicator_key: str):
    """Check if indicator key exists in intraday mapping."""
    return indicator_key.upper() in INTRADAY_INDICATOR_MAPPING
