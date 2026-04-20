"""Tests for the merged indicator compute path (v0.2.0).

These tests exercise _compute_indicators_for_contract and _validate_regime_params
directly, using mocked get_function that resolves to echolon's own bundled
calculators (interday/ta_lib.py etc.) — the monorepo calculator modules are not
on sys.path in the standalone echolon test environment.

Note on parameter names: the flat-dict indicator_list uses the same kwarg names
as the underlying TA-Lib wrapper functions (e.g. ``timeperiod`` for RSI, ``nbdevup``
for BBands). The tests below use those exact names so that the kwargs pass cleanly
through to the calculator without any param-name translation layer.
"""
import numpy as np
import pandas as pd
import pytest
from unittest.mock import patch


def _make_df(n=200):
    return pd.DataFrame({
        "open":   [100.0 + i * 0.1 for i in range(n)],
        "high":   [101.0 + i * 0.1 for i in range(n)],
        "low":    [99.0 + i * 0.1 for i in range(n)],
        "close":  [100.5 + i * 0.1 for i in range(n)],
        "volume": [1000 for _ in range(n)],
    })


def _echolon_get_function(indicator_key: str, frequency: str = "day"):
    """Resolve indicator functions directly from echolon's bundled calculators.

    The registry's get_function imports from ``modules.indicators.calculators.*``
    (a monorepo path).  In the standalone echolon test env that module tree is
    absent, so we import from ``echolon.indicators.calculators.*`` instead.
    """
    from echolon.indicators.calculators.interday import ta_lib as talib_module
    from echolon.indicators.calculators.interday import market_regime as regime_module

    MAPPING = {
        "RSI":           (talib_module, "rsi"),
        "ATR":           (talib_module, "atr"),
        "BBANDS":        (talib_module, "bbands"),
        "MACD":          (talib_module, "macd"),
        "MARKET_REGIME": (regime_module, "market_regime"),
    }
    entry = MAPPING.get(indicator_key.upper())
    if entry is None:
        return None
    module, func_name = entry
    return getattr(module, func_name, None)


def test_compute_produces_one_column_per_sweep_combo(interday_ctx):
    """indicator_list {"rsi": {"timeperiod": [5, 8]}} -> cols rsi_5, rsi_6, rsi_7, rsi_8."""
    from echolon.indicators.engine.processor import _compute_indicators_for_contract

    df = _make_df()
    # timeperiod is the RSI function's actual kwarg; range 5..8 -> 4 values
    indicator_list = {"rsi": {"timeperiod": [5, 8]}}

    with patch(
        "echolon.indicators.engine.processor.get_function",
        side_effect=_echolon_get_function,
    ):
        result = _compute_indicators_for_contract(df, indicator_list, ctx=interday_ctx)

    assert {"rsi_5", "rsi_6", "rsi_7", "rsi_8"}.issubset(result.keys())


def test_compute_cartesian_sweep_for_multi_param(interday_ctx):
    """{"bbands": {"timeperiod": [15, 17], "nbdevup": [1.5, 2.0]}} -> 3*2=6 combos (18 cols)."""
    from echolon.indicators.engine.processor import _compute_indicators_for_contract

    df = _make_df()
    # timeperiod=[15,16,17] × nbdevup=[1.5,2.0] = 6 combos; bbands returns 3 arrays each
    indicator_list = {"bbands": {"timeperiod": [15, 17], "nbdevup": [1.5, 2.0]}}

    with patch(
        "echolon.indicators.engine.processor.get_function",
        side_effect=_echolon_get_function,
    ):
        result = _compute_indicators_for_contract(df, indicator_list, ctx=interday_ctx)

    # BBands has 3 outputs per combo (upper, middle, lower)
    # 3 periods * 2 nbdevup values = 6 combos * 3 outputs = 18 cols minimum
    bbands_cols = [k for k in result if k.startswith("bbands_")]
    assert len(bbands_cols) >= 6 * 3


def test_compute_empty_params_uses_defaults(interday_ctx):
    """{"macd": {}} -> use library defaults, at least one macd-prefixed col."""
    from echolon.indicators.engine.processor import _compute_indicators_for_contract

    df = _make_df()
    indicator_list = {"macd": {}}

    with patch(
        "echolon.indicators.engine.processor.get_function",
        side_effect=_echolon_get_function,
    ):
        result = _compute_indicators_for_contract(df, indicator_list, ctx=interday_ctx)

    macd_cols = [k for k in result if k.startswith("macd")]
    assert len(macd_cols) >= 1


def test_compute_missing_market_regime_params_raises(interday_ctx):
    """market_regime without regime_params must raise — no silent defaults."""
    from echolon.indicators.engine.processor import _validate_regime_params

    with pytest.raises(ValueError, match="regime_params"):
        _validate_regime_params(
            indicator_list={"market_regime": {}},
            regime_params=None,
            ctx=interday_ctx,
        )


def test_compute_regime_params_passed_through(interday_ctx):
    """When caller provides regime_params + indicator_list contains market_regime,
    the params are merged into the market_regime call."""
    from echolon.indicators.engine.processor import _compute_indicators_for_contract

    df = _make_df()
    indicator_list = {"market_regime": {}}
    regime_params = {
        "fast_ma_period": 20, "slow_ma_period": 50,
        "adx_period": 14, "adx_trend_threshold": 20.0,
        "atr_period": 14, "vol_lookback": 60,
        "vol_high_percentile": 75.0,
        "chop_period": 14, "chop_threshold": 50.0,
        "min_regime_bars": 3,
    }

    with patch(
        "echolon.indicators.engine.processor.get_function",
        side_effect=_echolon_get_function,
    ):
        result = _compute_indicators_for_contract(
            df, indicator_list, ctx=interday_ctx, regime_params=regime_params,
        )

    assert "market_regime" in result or any(k.startswith("market_regime") for k in result)
