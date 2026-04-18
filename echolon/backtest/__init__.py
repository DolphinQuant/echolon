"""Echolon backtest engine — Backtrader wrapper, Optuna optimization, walk-forward analysis."""

from echolon.backtest.engine_factory import EngineFactory
from echolon.backtest.portfolio_runner import PortfolioBacktestRunner
from echolon.backtest.runner import run_backtest, run_best_trial, run_debug_backtest
from echolon.backtest.schemas import (
    BacktestResultsSchemaV4,
    SelectedTrialSchema,
)

__all__ = [
    "EngineFactory",
    "PortfolioBacktestRunner",
    "run_backtest",
    "run_best_trial",
    "run_debug_backtest",
    "BacktestResultsSchemaV4",
    "SelectedTrialSchema",
]
