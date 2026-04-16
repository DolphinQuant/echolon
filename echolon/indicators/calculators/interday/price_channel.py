import pandas as pd
import numpy as np
import talib
import logging

# Get logger for this module
logger = logging.getLogger(__name__)


def price_channel(df: pd.DataFrame,
                  timeperiod: int = 20,
                  indicator_name: str = None) -> np.ndarray:
    """
    Calculate price channel indicators (highest high or lowest low) based on indicator name.

    This function serves as a unified interface for both highest_high_N and lowest_low_N
    indicators, determined by the indicator_name parameter.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame containing OHLCV data
    period : int
        Period for price channel calculation (default: 20)
    indicator_name : str
        Indicator name to determine calculation type:
        - Contains 'highest_high': Returns highest high over period
        - Contains 'lowest_low': Returns lowest low over period

    Returns
    -------
    np.ndarray
        Price channel values (highest high or lowest low) over the specified period
    """
    if indicator_name and 'highest_high' in indicator_name.lower():
        # Calculate highest high using TA-Lib MAX function
        high = df['high'].values
        return talib.MAX(high, timeperiod=timeperiod)

    elif indicator_name and 'lowest_low' in indicator_name.lower():
        # Calculate lowest low using TA-Lib MIN function
        low = df['low'].values
        return talib.MIN(low, timeperiod=timeperiod)

    else:
        # Default behavior or unknown indicator name
        logger.warning(f"[PRICE_CHANNEL] Unknown indicator | name={indicator_name}, defaulting=highest_high")
        high = df['high'].values
        return talib.MAX(high, timeperiod=timeperiod)