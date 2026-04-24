"""
Indicator Mapping Configuration

This module provides mapping between indicator keys and their corresponding
utility function names for easy orchestration and function calling.
"""

INDICATOR_FILES = {
    "talib_indicator": "ta_lib",
    "market_regime": "market_regime",
    "sr_zone": "sr_zone",
    "price_channel": "price_channel"
}

# Indicator key to function name and cluster mapping
INDICATOR_MAPPING = {
    # Indicators with lookback period
    "ATR": {"function": "atr",
            "cluster": "indicators_with_lookback",
            "file": INDICATOR_FILES["talib_indicator"]},
    "ADX": {"function": "adx",
           "cluster": "indicators_with_lookback",
           "file": INDICATOR_FILES["talib_indicator"]},
    "ADXR": {"function": "adxr",
            "cluster": "indicators_with_lookback",
            "file": INDICATOR_FILES["talib_indicator"]},
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
    "MAX": {"function": "max_func", "cluster": "indicators_with_lookback", "file": INDICATOR_FILES["talib_indicator"]},
    "MAXINDEX": {"function": "maxindex", "cluster": "indicators_with_lookback", "file": INDICATOR_FILES["talib_indicator"]},
    "MIN": {"function": "min_func", "cluster": "indicators_with_lookback", "file": INDICATOR_FILES["talib_indicator"]},
    "MININDEX": {"function": "minindex", "cluster": "indicators_with_lookback", "file": INDICATOR_FILES["talib_indicator"]},
    "MINMAX_MIN": {"function": "minmax", "cluster": "indicators_with_lookback", "file": INDICATOR_FILES["talib_indicator"]},
    "MINMAX_MAX": {"function": "minmax", "cluster": "indicators_with_lookback", "file": INDICATOR_FILES["talib_indicator"]},
    "MINMAXINDEX_MIN": {"function": "minmaxindex", "cluster": "indicators_with_lookback", "file": INDICATOR_FILES["talib_indicator"]},
    "MINMAXINDEX_MAX": {"function": "minmaxindex", "cluster": "indicators_with_lookback", "file": INDICATOR_FILES["talib_indicator"]},
    "SUM": {"function": "sum_func", "cluster": "indicators_with_lookback", "file": INDICATOR_FILES["talib_indicator"]},
    "BETA": {"function": "beta", "cluster": "indicators_with_lookback", "file": INDICATOR_FILES["talib_indicator"]},
    "CORREL": {"function": "correl", "cluster": "indicators_with_lookback", "file": INDICATOR_FILES["talib_indicator"]},
    "LINEARREG": {"function": "linearreg", "cluster": "indicators_with_lookback", "file": INDICATOR_FILES["talib_indicator"]},
    "LINEARREG_ANGLE": {"function": "linearreg_angle", "cluster": "indicators_with_lookback", "file": INDICATOR_FILES["talib_indicator"]},
    "LINEARREG_INTERCEPT": {"function": "linearreg_intercept", "cluster": "indicators_with_lookback", "file": INDICATOR_FILES["talib_indicator"]},
    "LINEARREG_SLOPE": {"function": "linearreg_slope", "cluster": "indicators_with_lookback", "file": INDICATOR_FILES["talib_indicator"]},
    "TSF": {"function": "tsf", "cluster": "indicators_with_lookback", "file": INDICATOR_FILES["talib_indicator"]},
    "NATR": {"function": "natr", "cluster": "indicators_with_lookback", "file": INDICATOR_FILES["talib_indicator"]},
    "HIGHEST_HIGH": {"function": "price_channel", "cluster": "indicators_with_lookback", "file": INDICATOR_FILES["price_channel"]},
    "LOWEST_LOW": {"function": "price_channel", "cluster": "indicators_with_lookback", "file": INDICATOR_FILES["price_channel"]},

    # Indicators without lookback period
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
    "CDL2CROWS": {"function": "cdl2crows", "cluster": "indicators_without_lookback", "file": INDICATOR_FILES["talib_indicator"]},
    "CDL3BLACKCROWS": {"function": "cdl3blackcrows", "cluster": "indicators_without_lookback", "file": INDICATOR_FILES["talib_indicator"]},
    "CDL3INSIDE": {"function": "cdl3inside", "cluster": "indicators_without_lookback", "file": INDICATOR_FILES["talib_indicator"]},
    "CDL3LINESTRIKE": {"function": "cdl3linestrike", "cluster": "indicators_without_lookback", "file": INDICATOR_FILES["talib_indicator"]},
    "CDL3OUTSIDE": {"function": "cdl3outside", "cluster": "indicators_without_lookback", "file": INDICATOR_FILES["talib_indicator"]},
    "CDL3STARSINSOUTH": {"function": "cdl3starsinsouth", "cluster": "indicators_without_lookback", "file": INDICATOR_FILES["talib_indicator"]},
    "CDL3WHITESOLDIERS": {"function": "cdl3whitesoldiers", "cluster": "indicators_without_lookback", "file": INDICATOR_FILES["talib_indicator"]},
    "CDLADVANCEBLOCK": {"function": "cdladvanceblock", "cluster": "indicators_without_lookback", "file": INDICATOR_FILES["talib_indicator"]},
    "CDLBELTHOLD": {"function": "cdlbelthold", "cluster": "indicators_without_lookback", "file": INDICATOR_FILES["talib_indicator"]},
    "CDLBREAKAWAY": {"function": "cdlbreakaway", "cluster": "indicators_without_lookback", "file": INDICATOR_FILES["talib_indicator"]},
    "CDLCLOSINGMARUBOZU": {"function": "cdlclosingmarubozu", "cluster": "indicators_without_lookback", "file": INDICATOR_FILES["talib_indicator"]},
    "CDLCONCEALBABYSWALL": {"function": "cdlconcealbabyswall", "cluster": "indicators_without_lookback", "file": INDICATOR_FILES["talib_indicator"]},
    "CDLCOUNTERATTACK": {"function": "cdlcounterattack", "cluster": "indicators_without_lookback", "file": INDICATOR_FILES["talib_indicator"]},
    "CDLDOJI": {"function": "cdldoji", "cluster": "indicators_without_lookback", "file": INDICATOR_FILES["talib_indicator"]},
    "CDLDOJISTAR": {"function": "cdldojistar", "cluster": "indicators_without_lookback", "file": INDICATOR_FILES["talib_indicator"]},
    "CDLDRAGONFLYDOJI": {"function": "cdldragonflydoji", "cluster": "indicators_without_lookback", "file": INDICATOR_FILES["talib_indicator"]},
    "CDLENGULFING": {"function": "cdlengulfing", "cluster": "indicators_without_lookback", "file": INDICATOR_FILES["talib_indicator"]},
    "CDLGAPSIDESIDEWHITE": {"function": "cdlgapsidesidewhite", "cluster": "indicators_without_lookback", "file": INDICATOR_FILES["talib_indicator"]},
    "CDLGRAVESTONEDOJI": {"function": "cdlgravestonedoji", "cluster": "indicators_without_lookback", "file": INDICATOR_FILES["talib_indicator"]},
    "CDLHAMMER": {"function": "cdlhammer", "cluster": "indicators_without_lookback", "file": INDICATOR_FILES["talib_indicator"]},
    "CDLHANGINGMAN": {"function": "cdlhangingman", "cluster": "indicators_without_lookback", "file": INDICATOR_FILES["talib_indicator"]},
    "CDLHARAMI": {"function": "cdlharami", "cluster": "indicators_without_lookback", "file": INDICATOR_FILES["talib_indicator"]},
    "CDLHARAMICROSS": {"function": "cdlharamicross", "cluster": "indicators_without_lookback", "file": INDICATOR_FILES["talib_indicator"]},
    "CDLHIGHWAVE": {"function": "cdlhighwave", "cluster": "indicators_without_lookback", "file": INDICATOR_FILES["talib_indicator"]},
    "CDLHIKKAKE": {"function": "cdlhikkake", "cluster": "indicators_without_lookback", "file": INDICATOR_FILES["talib_indicator"]},
    "CDLHIKKAKEMOD": {"function": "cdlhikkakemod", "cluster": "indicators_without_lookback", "file": INDICATOR_FILES["talib_indicator"]},
    "CDLHOMINGPIGEON": {"function": "cdlhomingpigeon", "cluster": "indicators_without_lookback", "file": INDICATOR_FILES["talib_indicator"]},
    "CDLIDENTICAL3CROWS": {"function": "cdlidentical3crows", "cluster": "indicators_without_lookback", "file": INDICATOR_FILES["talib_indicator"]},
    "CDLINNECK": {"function": "cdlinneck", "cluster": "indicators_without_lookback", "file": INDICATOR_FILES["talib_indicator"]},
    "CDLINVERTEDHAMMER": {"function": "cdlinvertedhammer", "cluster": "indicators_without_lookback", "file": INDICATOR_FILES["talib_indicator"]},
    "CDLKICKING": {"function": "cdlkicking", "cluster": "indicators_without_lookback", "file": INDICATOR_FILES["talib_indicator"]},
    "CDLKICKINGBYLENGTH": {"function": "cdlkickingbylength", "cluster": "indicators_without_lookback", "file": INDICATOR_FILES["talib_indicator"]},
    "CDLLADDERBOTTOM": {"function": "cdlladderbottom", "cluster": "indicators_without_lookback", "file": INDICATOR_FILES["talib_indicator"]},
    "CDLLONGLEGGEDDOJI": {"function": "cdllongleggeddoji", "cluster": "indicators_without_lookback", "file": INDICATOR_FILES["talib_indicator"]},
    "CDLLONGLINE": {"function": "cdllongline", "cluster": "indicators_without_lookback", "file": INDICATOR_FILES["talib_indicator"]},
    "CDLMARUBOZU": {"function": "cdlmarubozu", "cluster": "indicators_without_lookback", "file": INDICATOR_FILES["talib_indicator"]},
    "CDLMATCHINGLOW": {"function": "cdlmatchinglow", "cluster": "indicators_without_lookback", "file": INDICATOR_FILES["talib_indicator"]},
    "CDLONNECK": {"function": "cdlonneck", "cluster": "indicators_without_lookback", "file": INDICATOR_FILES["talib_indicator"]},
    "CDLPIERCING": {"function": "cdlpiercing", "cluster": "indicators_without_lookback", "file": INDICATOR_FILES["talib_indicator"]},
    "CDLRICKSHAWMAN": {"function": "cdlrickshawman", "cluster": "indicators_without_lookback", "file": INDICATOR_FILES["talib_indicator"]},
    "CDLRISEFALL3METHODS": {"function": "cdlrisefall3methods", "cluster": "indicators_without_lookback", "file": INDICATOR_FILES["talib_indicator"]},
    "CDLSEPARATINGLINES": {"function": "cdlseparatinglines", "cluster": "indicators_without_lookback", "file": INDICATOR_FILES["talib_indicator"]},
    "CDLSHOOTINGSTAR": {"function": "cdlshootingstar", "cluster": "indicators_without_lookback", "file": INDICATOR_FILES["talib_indicator"]},
    "CDLSHORTLINE": {"function": "cdlshortline", "cluster": "indicators_without_lookback", "file": INDICATOR_FILES["talib_indicator"]},
    "CDLSPINNINGTOP": {"function": "cdlspinningtop", "cluster": "indicators_without_lookback", "file": INDICATOR_FILES["talib_indicator"]},
    "CDLSTALLEDPATTERN": {"function": "cdlstalledpattern", "cluster": "indicators_without_lookback", "file": INDICATOR_FILES["talib_indicator"]},
    "CDLSTICKSANDWICH": {"function": "cdlsticksandwich", "cluster": "indicators_without_lookback", "file": INDICATOR_FILES["talib_indicator"]},
    "CDLTAKURI": {"function": "cdltakuri", "cluster": "indicators_without_lookback", "file": INDICATOR_FILES["talib_indicator"]},
    "CDLTASUKIGAP": {"function": "cdltasukigap", "cluster": "indicators_without_lookback", "file": INDICATOR_FILES["talib_indicator"]},
    "CDLTHRUSTING": {"function": "cdlthrusting", "cluster": "indicators_without_lookback", "file": INDICATOR_FILES["talib_indicator"]},
    "CDLTRISTAR": {"function": "cdltristar", "cluster": "indicators_without_lookback", "file": INDICATOR_FILES["talib_indicator"]},
    "CDLUNIQUE3RIVER": {"function": "cdlunique3river", "cluster": "indicators_without_lookback", "file": INDICATOR_FILES["talib_indicator"]},
    "CDLUPSIDEGAP2CROWS": {"function": "cdlupsidegap2crows", "cluster": "indicators_without_lookback", "file": INDICATOR_FILES["talib_indicator"]},
    "CDLXSIDEGAP3METHODS": {"function": "cdlxsidegap3methods", "cluster": "indicators_without_lookback", "file": INDICATOR_FILES["talib_indicator"]},
    "HT_DCPERIOD": {"function": "ht_dcperiod", "cluster": "indicators_without_lookback", "file": INDICATOR_FILES["talib_indicator"]},
    "HT_DCPHASE": {"function": "ht_dcphase", "cluster": "indicators_without_lookback", "file": INDICATOR_FILES["talib_indicator"]},
    "HT_PHASOR_INPHASE": {"function": "ht_phasor", "cluster": "indicators_without_lookback", "file": INDICATOR_FILES["talib_indicator"]},
    "HT_PHASOR_QUADRATURE": {"function": "ht_phasor", "cluster": "indicators_without_lookback", "file": INDICATOR_FILES["talib_indicator"]},
    "HT_SINE": {"function": "ht_sine", "cluster": "indicators_without_lookback", "file": INDICATOR_FILES["talib_indicator"]},
    "HT_LEADSINE": {"function": "ht_sine", "cluster": "indicators_without_lookback", "file": INDICATOR_FILES["talib_indicator"]},
    "HT_TRENDMODE": {"function": "ht_trendmode", "cluster": "indicators_without_lookback", "file": INDICATOR_FILES["talib_indicator"]},
    "HT_TRENDLINE": {"function": "ht_trendline", "cluster": "indicators_without_lookback", "file": INDICATOR_FILES["talib_indicator"]},

    # Indicators with special parameters
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
    "BBANDS_PCT_B": {"function": "bbands_pct_b", "cluster": "indicators_with_special_params", "file": INDICATOR_FILES["talib_indicator"]},
    "BBANDS_BANDWIDTH": {"function": "bbands_bandwidth", "cluster": "indicators_with_special_params", "file": INDICATOR_FILES["talib_indicator"]},
    "MAMA": {"function": "mama", "cluster": "indicators_with_special_params", "file": INDICATOR_FILES["talib_indicator"]},
    "FAMA": {"function": "mama", "cluster": "indicators_with_special_params", "file": INDICATOR_FILES["talib_indicator"]},
    "MAVP": {"function": "mavp", "cluster": "indicators_with_special_params", "file": INDICATOR_FILES["talib_indicator"]},
    "SAR": {"function": "sar", "cluster": "indicators_with_special_params", "file": INDICATOR_FILES["talib_indicator"]},
    "SAREXT": {"function": "sarext", "cluster": "indicators_with_special_params", "file": INDICATOR_FILES["talib_indicator"]},
    "T3": {"function": "t3", "cluster": "indicators_with_special_params", "file": INDICATOR_FILES["talib_indicator"]},
    "STDDEV": {"function": "stddev", "cluster": "indicators_with_special_params", "file": INDICATOR_FILES["talib_indicator"]},
    "VAR": {"function": "var", "cluster": "indicators_with_special_params", "file": INDICATOR_FILES["talib_indicator"]},
    "CDLABANDONEDBABY": {"function": "cdlabandonedbaby", "cluster": "indicators_with_special_params", "file": INDICATOR_FILES["talib_indicator"]},
    "CDLDARKCLOUDCOVER": {"function": "cdldarkcloudcover", "cluster": "indicators_with_special_params", "file": INDICATOR_FILES["talib_indicator"]},
    "CDLEVENINGDOJISTAR": {"function": "cdleveningdojistar", "cluster": "indicators_with_special_params", "file": INDICATOR_FILES["talib_indicator"]},
    "CDLEVENINGSTAR": {"function": "cdleveningstar", "cluster": "indicators_with_special_params", "file": INDICATOR_FILES["talib_indicator"]},
    "CDLMATHOLD": {"function": "cdlmathold", "cluster": "indicators_with_special_params", "file": INDICATOR_FILES["talib_indicator"]},
    "CDLMORNINGDOJISTAR": {"function": "cdlmorningdojistar", "cluster": "indicators_with_special_params", "file": INDICATOR_FILES["talib_indicator"]},
    "CDLMORNINGSTAR": {"function": "cdlmorningstar", "cluster": "indicators_with_special_params", "file": INDICATOR_FILES["talib_indicator"]},
    "MARKET_REGIME": {"function": "market_regime", "cluster": "indicators_with_special_params", "file": INDICATOR_FILES["market_regime"]},
    "SR_ZONE_LEVEL": {"function": "support_resistance_zones", "cluster": "indicators_with_special_params", "file": INDICATOR_FILES["sr_zone"]},
    "SR_ZONE_TYPE": {"function": "support_resistance_zones", "cluster": "indicators_with_special_params", "file": INDICATOR_FILES["sr_zone"]},
    "SR_ZONE_STRENGTH": {"function": "support_resistance_zones", "cluster": "indicators_with_special_params", "file": INDICATOR_FILES["sr_zone"]},
    "SR_ZONE_DISTANCE_PCT": {"function": "support_resistance_zones", "cluster": "indicators_with_special_params", "file": INDICATOR_FILES["sr_zone"]},
    "ADOSC": {"function": "adosc", "cluster": "indicators_with_special_params", "file": INDICATOR_FILES["talib_indicator"]}
}

# Function to get indicators by cluster
def get_indicators_by_cluster(cluster_name):
    """Get list of indicators in a specific cluster"""
    return [key for key, value in INDICATOR_MAPPING.items() if value["cluster"] == cluster_name]

# Function to get all clusters
def get_all_clusters():
    """Return list of all indicator clusters"""
    return list(set(value["cluster"] for value in INDICATOR_MAPPING.values()))

# Function to get all available indicator keys
def get_all_indicator_keys():
    """Return list of all available indicator keys"""
    return list(INDICATOR_MAPPING.keys())

# Function to get the actual function by indicator key
def get_function(indicator_key, frequency: str = "day"):
    """
    Get the actual indicator function by indicator key.

    Routes to appropriate calculator based on frequency:
    - Interday (day/daily): Uses interday calculators with interday mapping
    - Intraday (minute): Uses intraday calculators with intraday mapping

    Args:
        indicator_key: Indicator name (e.g., 'RSI', 'MACD_LINE', 'VWAP')
        frequency: Data frequency ('day' for interday, 'minute' for intraday)

    Returns:
        Function from the appropriate calculator module
    """
    import importlib

    # Route to intraday-specific mapping for intraday frequencies
    if frequency in ("minute", "intraday"):
        from . import intraday_indicator_mapping
        return intraday_indicator_mapping.get_function(indicator_key)

    # Use interday mapping (default)
    mapping = INDICATOR_MAPPING.get(indicator_key.upper())
    if not mapping:
        return None

    function_name = mapping["function"]
    file_name = mapping.get("file", INDICATOR_FILES["talib_indicator"])

    # Import from interday calculators
    module = importlib.import_module(
        f"echolon.indicators.calculators.interday.{file_name}"
    )

    # Get the function from the module
    return getattr(module, function_name, None)

# Keep the old function for backward compatibility
def get_function_name(indicator_key):
    """Get function name by indicator key (deprecated, use get_function instead)"""
    mapping = INDICATOR_MAPPING.get(indicator_key.upper())
    return mapping["function"] if mapping else None

# Function to get cluster name by indicator key
def get_cluster_name(indicator_key):
    """Get cluster name by indicator key"""
    mapping = INDICATOR_MAPPING.get(indicator_key.upper())
    return mapping["cluster"] if mapping else None

# Function to get both function and cluster by indicator key
def get_indicator_info(indicator_key, frequency: str = "day"):
    """
    Get both function name and cluster by indicator key.

    Args:
        indicator_key: Indicator name (e.g., 'RSI', 'VWAP')
        frequency: Data frequency ('day' for interday, 'minute' for intraday)

    Returns:
        Dict with 'function', 'cluster', and 'file' keys
    """
    # Route to intraday mapping for intraday frequencies
    if frequency in ("minute", "intraday"):
        from . import intraday_indicator_mapping
        return intraday_indicator_mapping.get_indicator_info(indicator_key)

    # Use interday mapping (default)
    return INDICATOR_MAPPING.get(indicator_key.upper())

# Function to check if indicator exists
def indicator_exists(indicator_key):
    """Check if indicator key exists in mapping"""
    return indicator_key.upper() in INDICATOR_MAPPING