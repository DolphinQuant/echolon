"""
Merge Indicator Lists
=====================

Utility for creating a union of N indicator list configs with
min/max lookback range merging.

Used by PortfolioTradingRunner when multiple strategies on the same
instrument need different indicators calculated on the same data.
"""

import json
from typing import Any, Dict, List


def merge_indicator_lists(configs: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Union N indicator configs into one, merging lookback ranges.

    Each config follows the strategy_indicator_list.json schema:
    {
        "indicators_with_lookback": {"RSI": [7, 21], "ATR": [10, 30]},
        "indicators_without_lookback": ["MACD", "BBANDS"],
        "indicators_with_special_params": ["REGIME"]
    }

    For indicators_with_lookback, the merged range uses
    min(all mins) and max(all maxes).

    Returns:
        Merged indicator config dict.
    """
    merged_lookback: Dict[str, List[int]] = {}
    merged_no_lookback: set = set()
    merged_special: set = set()

    for cfg in configs:
        # Merge lookback indicators
        for name, range_vals in cfg.get('indicators_with_lookback', {}).items():
            if name in merged_lookback:
                existing = merged_lookback[name]
                merged_lookback[name] = [
                    min(existing[0], range_vals[0]),
                    max(existing[1], range_vals[1]),
                ]
            else:
                merged_lookback[name] = list(range_vals)

        # Merge no-lookback
        for name in cfg.get('indicators_without_lookback', []):
            merged_no_lookback.add(name)

        # Merge special
        for name in cfg.get('indicators_with_special_params', []):
            merged_special.add(name)

    return {
        'indicators_with_lookback': merged_lookback,
        'indicators_without_lookback': sorted(merged_no_lookback),
        'indicators_with_special_params': sorted(merged_special),
    }


def load_indicator_list(path: str) -> Dict[str, Any]:
    """Load a strategy_indicator_list.json file."""
    with open(path, 'r') as f:
        return json.load(f)
