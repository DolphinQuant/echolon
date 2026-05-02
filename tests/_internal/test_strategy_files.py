"""Phase E paradigm-decoupling: calculator_params.json file format tests.

The new ``calculator_params.json`` format generalizes ``regime_params.json``
to support any registered classifier under one schema. Legacy strategies
in ``output_bank/`` ship ``regime_params.json`` and must continue to load
without manual migration.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from echolon._internal.strategy_files import (
    load_calculator_params,
    save_calculator_params,
    get_regime_params,
)


# ---------------------------------------------------------------------------
# New format
# ---------------------------------------------------------------------------


def test_load_new_format(tmp_path: Path):
    """calculator_params.json with version=1 schema → returns calculators dict."""
    payload = {
        "version": 1,
        "calculators": {
            "market_regime": {"fast_ma_period": 20, "slow_ma_period": 50},
            "future_carry": {"lookback": 60},
        },
    }
    (tmp_path / "calculator_params.json").write_text(json.dumps(payload))
    assert load_calculator_params(tmp_path) == payload["calculators"]


def test_save_writes_new_format(tmp_path: Path):
    cp = {"market_regime": {"fast_ma_period": 12}}
    out = save_calculator_params(tmp_path, cp)
    assert out.name == "calculator_params.json"
    written = json.loads(out.read_text())
    assert written["version"] == 1
    assert written["calculators"] == cp


def test_round_trip_new_format(tmp_path: Path):
    cp = {"market_regime": {"adx_period": 14}}
    save_calculator_params(tmp_path, cp)
    assert load_calculator_params(tmp_path) == cp


# ---------------------------------------------------------------------------
# Legacy auto-migration
# ---------------------------------------------------------------------------


def test_legacy_wrapped_format_auto_migrates(tmp_path: Path):
    """Legacy regime_params.json with {"params": {...}} wrapper → migrates to
    {"market_regime": {...}}."""
    legacy = {"params": {"fast_ma_period": 12, "slow_ma_period": 30}}
    (tmp_path / "regime_params.json").write_text(json.dumps(legacy))
    result = load_calculator_params(tmp_path)
    assert result == {"market_regime": legacy["params"]}


def test_legacy_flat_format_auto_migrates(tmp_path: Path):
    """Legacy regime_params.json with flat {...} → migrates to {"market_regime": {...}}."""
    legacy = {"fast_ma_period": 12, "slow_ma_period": 30}
    (tmp_path / "regime_params.json").write_text(json.dumps(legacy))
    result = load_calculator_params(tmp_path)
    assert result == {"market_regime": legacy}


def test_new_format_takes_precedence_over_legacy(tmp_path: Path):
    """When both files exist, calculator_params.json wins."""
    new = {"version": 1, "calculators": {"market_regime": {"adx_period": 99}}}
    legacy = {"params": {"adx_period": 14}}
    (tmp_path / "calculator_params.json").write_text(json.dumps(new))
    (tmp_path / "regime_params.json").write_text(json.dumps(legacy))
    result = load_calculator_params(tmp_path)
    assert result["market_regime"]["adx_period"] == 99


# ---------------------------------------------------------------------------
# Empty / missing
# ---------------------------------------------------------------------------


def test_no_files_returns_empty(tmp_path: Path):
    """Strategy directory with no params file → empty dict (not error)."""
    assert load_calculator_params(tmp_path) == {}


def test_get_regime_params_returns_none_when_absent(tmp_path: Path):
    assert get_regime_params(tmp_path) is None


def test_get_regime_params_extracts_market_regime_from_legacy(tmp_path: Path):
    legacy = {"params": {"fast_ma_period": 12}}
    (tmp_path / "regime_params.json").write_text(json.dumps(legacy))
    assert get_regime_params(tmp_path) == legacy["params"]


def test_get_regime_params_extracts_market_regime_from_new(tmp_path: Path):
    new = {"version": 1, "calculators": {"market_regime": {"adx_period": 14}}}
    (tmp_path / "calculator_params.json").write_text(json.dumps(new))
    assert get_regime_params(tmp_path) == {"adx_period": 14}


def test_get_regime_params_returns_none_when_only_other_calculators(tmp_path: Path):
    """When calculator_params.json has only e.g. future_carry, market_regime returns None."""
    new = {"version": 1, "calculators": {"future_carry": {"lookback": 60}}}
    (tmp_path / "calculator_params.json").write_text(json.dumps(new))
    assert get_regime_params(tmp_path) is None


# ---------------------------------------------------------------------------
# Path/string flexibility
# ---------------------------------------------------------------------------


def test_accepts_string_path(tmp_path: Path):
    legacy = {"params": {"x": 1}}
    (tmp_path / "regime_params.json").write_text(json.dumps(legacy))
    result = load_calculator_params(str(tmp_path))
    assert result == {"market_regime": legacy["params"]}
