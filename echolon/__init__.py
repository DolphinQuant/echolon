"""Echolon — See what others can't. Market-agnostic quantitative trading engine."""

__version__ = "0.1.1"

# Errors
from echolon.errors import EchelonError

# Configs
from echolon.config.backtest_config import BacktestConfig
from echolon.config.indicator_config import IndicatorConfig
from echolon.config.markets.core.context import TradingContext
from echolon.config.optuna_config import OptunaConfig
from echolon.config.quick_start import quick_start

# Schemas (most commonly used)
from echolon.strategy.schemas import (
    EntrySignalOutput,
    ExitSignalOutput,
    OrderIntent,
    RiskOutput,
    SizerOutput,
)

# Convenience entry points
from echolon.backtest.runner import run_backtest
from echolon.data.backtest_data import run_data_pipeline

__all__ = [
    "__version__",
    # Errors
    "EchelonError",
    # Configs
    "BacktestConfig",
    "IndicatorConfig",
    "OptunaConfig",
    "TradingContext",
    "quick_start",
    # Schemas
    "EntrySignalOutput",
    "ExitSignalOutput",
    "OrderIntent",
    "RiskOutput",
    "SizerOutput",
    # Entry points
    "run_backtest",
    "run_data_pipeline",
]
