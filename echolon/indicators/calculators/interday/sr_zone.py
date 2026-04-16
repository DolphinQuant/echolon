
import pandas as pd
import numpy as np
import logging
from typing import Union, Tuple

# Get logger for this module
logger = logging.getLogger(__name__)

def support_resistance_zones(df: pd.DataFrame,
                            lookback_period: int = 50,
                            zone_tolerance: float = 0.5,
                            min_touches: int = 3,
                            indicator_name: str = None) -> Union[np.ndarray, Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]]:
    """
    Calculate support and resistance zone indicators based on price action.

    Uses a rolling window approach to identify horizontal price levels that act as
    support or resistance based on historical price action.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame with OHLCV data
    lookback_period : int
        Period to look back for zone identification (default: 50)
    zone_tolerance : float
        Tolerance percentage for grouping prices into zones (default: 0.5%)
    min_touches : int
        Minimum number of touches required for a valid zone (default: 3)
    indicator_name : str
        Optional indicator name for selective return ('SR_ZONE_LEVEL', 'SR_ZONE_TYPE',
        'SR_ZONE_STRENGTH', 'SR_ZONE_DISTANCE_PCT')

    Returns
    -------
    Union[np.ndarray, Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]]
        If indicator_name is specified: returns the selected indicator array
        Otherwise: returns tuple of (zone_level, zone_type, zone_strength, zone_distance_pct)
    """
    # Extract required data
    high = df['high'].values
    low = df['low'].values
    close = df['close'].values

    # Initialize arrays with default values
    length = len(df)
    zone_level = np.full(length, np.nan, dtype=np.float64)
    zone_type = np.zeros(length, dtype=np.float64)  # 1 = resistance, -1 = support, 0 = no zone
    zone_strength = np.zeros(length, dtype=np.float64)
    zone_distance_pct = np.full(length, np.nan, dtype=np.float64)

    def find_zones_in_window(window_high, window_low, current_close):
        """
        Find support and resistance zones in a price window.

        Parameters
        ----------
        window_high : np.ndarray
            Window of high prices
        window_low : np.ndarray
            Window of low prices
        current_close : float
            Current closing price

        Returns
        -------
        dict or None
            Dictionary with zone information or None if no zone found
        """
        if len(window_high) < min_touches * 2:
            return None

        # Combine all price points for clustering
        all_prices = np.concatenate([window_high, window_low])

        # Simple clustering based on tolerance
        tolerance_amount = current_close * (zone_tolerance / 100)

        # Group prices into zones
        zones = []
        used_prices = set()

        for price in sorted(set(all_prices)):
            if price in used_prices:
                continue

            # Find all prices within tolerance of this price
            zone_prices = []
            for p in all_prices:
                if abs(p - price) <= tolerance_amount:
                    zone_prices.append(p)
                    used_prices.add(p)

            # Only consider zones with minimum touches
            if len(zone_prices) >= min_touches:
                zone_level_val = np.mean(zone_prices)
                zone_strength_val = len(zone_prices)

                # Determine zone type based on current price
                zone_type_val = 1 if zone_level_val > current_close else -1  # 1=resistance, -1=support

                # Calculate distance from current price
                distance_pct_val = abs(zone_level_val - current_close) / current_close * 100

                zones.append({
                    'level': zone_level_val,
                    'type': zone_type_val,
                    'strength': zone_strength_val,
                    'distance_pct': distance_pct_val
                })

        # Return the strongest zone (most touches)
        if zones:
            return sorted(zones, key=lambda x: x['strength'], reverse=True)[0]
        return None

    # Calculate S/R zones using rolling windows
    for i in range(lookback_period, length):
        window_start = max(0, i - lookback_period)
        window_end = i + 1

        window_high = high[window_start:window_end]
        window_low = low[window_start:window_end]
        current_close = close[i]

        zone = find_zones_in_window(window_high, window_low, current_close)

        if zone:
            zone_level[i] = zone['level']
            zone_type[i] = zone['type']
            zone_strength[i] = zone['strength']
            zone_distance_pct[i] = zone['distance_pct']

    # Handle selective return based on indicator_name
    if indicator_name:
        indicator_name = indicator_name.upper()
        if 'LEVEL' in indicator_name:
            return zone_level
        elif 'TYPE' in indicator_name:
            return zone_type
        elif 'STRENGTH' in indicator_name:
            return zone_strength
        elif 'DISTANCE' in indicator_name or 'PCT' in indicator_name:
            return zone_distance_pct

    # Return all indicators as tuple
    return zone_level, zone_type, zone_strength, zone_distance_pct


