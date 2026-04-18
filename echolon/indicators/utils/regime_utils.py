"""
Unified Market Regime Mapping Utilities

Provides standardized regime conversion between numeric and string formats.
Used across market_metrics, backtest_metrics, and LLM insight modules.
"""

import logging
import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# =============================================================================
# CANONICAL REGIME MAPPINGS
# =============================================================================

# Numeric to string mapping
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

# String to numeric mapping (for backtrader compatibility)
REGIME_STRING_TO_NUMERIC = {
    'trending_up': 1,
    'trending_down': -1,
    'ranging': 0,
    'volatile': 2
}

# String normalization mapping (handles various formats)
REGIME_STRING_NORMALIZATION = {
    'trending up': 'trending_up',
    'trending down': 'trending_down',
    'trending_up': 'trending_up',
    'trending_down': 'trending_down',
    'ranging': 'ranging',
    'volatile': 'volatile',
    'unknown': 'unknown',
    'mixed': 'mixed',
    'trending': 'trending',
    # String numeric values
    '1': 'trending_up',
    '1.0': 'trending_up',
    '-1': 'trending_down',
    '-1.0': 'trending_down',
    '0': 'ranging',
    '0.0': 'ranging',
    '2': 'volatile',
    '2.0': 'volatile',
    # Extended regime types
    'low_volatility': 'low_volatility',
    'high_volatility': 'high_volatility',
    'sideways': 'sideways',
    'strong_bullish': 'strong_bullish',
    'strong_bearish': 'strong_bearish',
    'neutral': 'neutral'
}


def convert_regime_to_string(regime_value) -> str:
    """
    Convert regime value to standardized string format.

    Handles:
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
        Standardized regime string
    """
    # Handle NaN/None values
    if pd.isna(regime_value) or regime_value is None:
        return 'unknown'

    # Handle numeric values
    if isinstance(regime_value, (int, float, np.integer, np.floating)) and not pd.isna(regime_value):
        if isinstance(regime_value, np.integer):
            regime_value = int(regime_value)
        elif isinstance(regime_value, np.floating):
            regime_value = float(regime_value)
        return REGIME_NUMERIC_TO_STRING.get(regime_value, 'unknown')

    # Handle string values
    if isinstance(regime_value, str):
        if regime_value in REGIME_STRING_NORMALIZATION:
            return REGIME_STRING_NORMALIZATION[regime_value]

        regime_value_lower = regime_value.lower()
        if regime_value_lower in REGIME_STRING_NORMALIZATION:
            return REGIME_STRING_NORMALIZATION[regime_value_lower]

        if regime_value_lower in ['trending_up', 'trending_down', 'ranging', 'volatile', 'unknown']:
            return regime_value_lower

    logger.warning(f"Unknown regime value: {regime_value} (type: {type(regime_value)}). Returning 'unknown'.")
    return 'unknown'


def convert_regime_to_numeric(regime_value) -> int:
    """
    Convert regime value to numeric format.

    Parameters
    ----------
    regime_value : str, int, float, or None
        Regime value to convert

    Returns
    -------
    int
        Numeric regime value (1, -1, 0, 2) or 0 for unknown
    """
    if pd.isna(regime_value) or regime_value is None:
        return 0

    if isinstance(regime_value, (int, float, np.integer, np.floating)):
        return int(regime_value)

    if isinstance(regime_value, str):
        string_val = convert_regime_to_string(regime_value)
        return REGIME_STRING_TO_NUMERIC.get(string_val, 0)

    return 0


def prepare_regime_data(df: pd.DataFrame) -> pd.DataFrame:
    """
    Prepare and validate market regime data from a dataframe.
    Converts regimes to standardized string format.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame with 'market_regime' column

    Returns
    -------
    pd.DataFrame
        DataFrame with added 'market_regime_string' column
    """
    df = df.copy()
    if 'market_regime' in df.columns:
        df['market_regime_string'] = df['market_regime'].apply(convert_regime_to_string)
    return df
