"""Echolon — See what others can't. Market-agnostic quantitative trading engine."""

__version__ = "0.1.0"

from echolon.config.backtest_config import BacktestConfig
from echolon.config.indicator_config import IndicatorConfig
from echolon.config.markets.core.context import TradingContext
from echolon.config.optuna_config import OptunaConfig
from echolon.config.quick_start import quick_start

__all__ = [
    "__version__",
    "BacktestConfig",
    "IndicatorConfig",
    "OptunaConfig",
    "TradingContext",
    "quick_start",
]
