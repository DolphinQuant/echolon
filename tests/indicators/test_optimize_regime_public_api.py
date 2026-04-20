"""Verify echolon.indicators.optimize_regime_params is a public callable."""
import inspect


def test_optimize_regime_params_is_importable_from_top_level():
    """User should: from echolon.indicators import optimize_regime_params"""
    from echolon.indicators import optimize_regime_params
    assert callable(optimize_regime_params)


def test_optimize_regime_params_signature_has_ctx_and_trials():
    from echolon.indicators import optimize_regime_params
    sig = inspect.signature(optimize_regime_params)
    assert "ctx" in sig.parameters
    assert "n_trials" in sig.parameters
    # n_trials should have a default so callers can omit it
    assert sig.parameters["n_trials"].default is not inspect.Parameter.empty
