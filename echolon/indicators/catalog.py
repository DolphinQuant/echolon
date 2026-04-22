"""Indicator catalog — programmatic introspection of indicators echolon ships.

Exposes list_all(), info(name), auto_generate_list(strategy_dir).
"""
from dataclasses import dataclass
from pathlib import Path


@dataclass
class IndicatorInfo:
    name: str
    tier: int  # 1 = period-named, 2 = special, 3 = no-lookback
    params: list[str]
    output_columns: list[str]


# Minimal hardcoded catalog seed; extend as the engine grows. If echolon has an
# existing registry (e.g., in ta_lib.py or indicator modules), import it instead.
_CATALOG: dict[str, IndicatorInfo] = {
    "rsi": IndicatorInfo(name="rsi", tier=1, params=["period"], output_columns=["rsi_{period}"]),
    "atr": IndicatorInfo(name="atr", tier=1, params=["period"], output_columns=["atr_{period}"]),
    "adx": IndicatorInfo(name="adx", tier=1, params=["period"], output_columns=["adx_{period}"]),
    "macd": IndicatorInfo(name="macd", tier=2, params=["fast", "slow", "signal"],
                          output_columns=["macd_line", "macd_signal", "macd_histogram"]),
    "bbands": IndicatorInfo(name="bbands", tier=2, params=["period", "nbdevup", "nbdevdn"],
                            output_columns=["bbands_upper", "bbands_middle", "bbands_lower"]),
    "ad": IndicatorInfo(name="ad", tier=3, params=[], output_columns=["ad"]),
    "obv": IndicatorInfo(name="obv", tier=3, params=[], output_columns=["obv"]),
}


def list_all() -> list[str]:
    """Return all known indicator names, sorted."""
    return sorted(_CATALOG.keys())


def info(name: str) -> IndicatorInfo | None:
    """Return IndicatorInfo for a name, or None if unknown."""
    return _CATALOG.get(name.lower())


def auto_generate_list(strategy_dir: Path) -> dict:
    """Scan strategy code for indicator usage; emit a canonical indicator list.

    Placeholder stub for Phase 1; full implementation in workstream E (Task 22).
    """
    return {"indicators": [], "indicators_with_special_params": []}
