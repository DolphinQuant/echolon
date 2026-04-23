"""Phase P2 — echolon public entry points accept paths= kwarg.

Coverage test enforcing the plan's P2 contract: every function a host project
(qorka) calls to drive data pipeline / indicators / backtest / live orchestration
must accept ``paths: PathsConfig | None``. Explicit injection is the intended
pattern; reflex ``PathsConfig.from_env()`` stays as an end-user fallback.
"""
import inspect

import pytest


def _signature_accepts_paths(fn) -> bool:
    """Return True iff the callable has a 'paths' parameter."""
    try:
        sig = inspect.signature(fn)
    except (ValueError, TypeError):
        return False
    return "paths" in sig.parameters


def test_run_data_pipeline_accepts_paths():
    from echolon.data.backtest_data import run_data_pipeline
    assert _signature_accepts_paths(run_data_pipeline)


def test_run_live_data_update_accepts_paths():
    from echolon.data.live_data import run_live_data_update
    assert _signature_accepts_paths(run_live_data_update)


def test_run_indicator_calculation_accepts_paths():
    from echolon.indicators.run import run_indicator_calculation
    assert _signature_accepts_paths(run_indicator_calculation)


def test_run_backtest_accepts_paths():
    from echolon.backtest.runner import run_backtest
    assert _signature_accepts_paths(run_backtest)


def test_run_debug_backtest_accepts_paths():
    from echolon.backtest.runner import run_debug_backtest
    assert _signature_accepts_paths(run_debug_backtest)


def test_run_best_trial_accepts_paths():
    from echolon.backtest.runner import run_best_trial
    assert _signature_accepts_paths(run_best_trial)


def test_wfa_runner_init_accepts_paths():
    from echolon.backtest.wfa.runner import WFARunner
    assert _signature_accepts_paths(WFARunner.__init__)


def test_optuna_optimizer_init_accepts_paths():
    from echolon.backtest.optimization.optuna_study import OptunaOptimizer
    assert _signature_accepts_paths(OptunaOptimizer.__init__)


def test_optimize_regime_params_accepts_paths():
    from echolon.indicators.optimization.interday_regime_optimizer import optimize_regime_params
    assert _signature_accepts_paths(optimize_regime_params)


def test_market_factory_from_session_accepts_paths():
    """Convenience — from_session accepts `paths=` as a single-arg alternative
    to the separate session_dir + output_dir kwargs."""
    from echolon.config.markets.factory import MarketFactory
    assert _signature_accepts_paths(MarketFactory.from_session)


def test_market_factory_load_target_accepts_paths():
    from echolon.config.markets.factory import MarketFactory
    assert _signature_accepts_paths(MarketFactory.load_target)


def test_trading_target_load_accepts_paths():
    from echolon.config.markets.core.trading_target import TradingTarget
    assert _signature_accepts_paths(TradingTarget.load)
