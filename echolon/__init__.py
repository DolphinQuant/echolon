"""Echolon — See what others can't. Market-agnostic quantitative trading engine."""

__version__ = "0.2.0"

from echolon.config.backtest_config import BacktestConfig
from echolon.config.indicator_config import IndicatorConfig
from echolon.config.markets.core.context import TradingContext
from echolon.config.optuna_config import OptunaConfig
from echolon.config.quick_start import quick_start
from echolon.native.validation.errors import EchelonError

__all__ = [
    "__version__",
    "BacktestConfig",
    "EchelonError",
    "IndicatorConfig",
    "OptunaConfig",
    "TradingContext",
    "quick_start",
]
