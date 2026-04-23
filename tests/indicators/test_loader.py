"""Tests for echolon/indicators/utils/loader.py::load_indicator_list."""
import json

import pytest

from echolon.indicators.utils.loader import load_indicator_list


def test_load_flat_dict_returns_flat_dict(tmp_path):
    p = tmp_path / "strategy_indicator_list.json"
    payload = {"rsi": {"timeperiod": [10, 20]}, "obv": {}}
    p.write_text(json.dumps(payload))
    out = load_indicator_list(str(p))
    assert out == payload


def test_load_rejects_unknown_indicator_name(tmp_path):
    """The catalog-aware schema rejects unknown names at load time."""
    p = tmp_path / "strategy_indicator_list.json"
    p.write_text(json.dumps({"unknown_indicator_name_xyz": {}}))
    with pytest.raises(Exception):
        load_indicator_list(str(p))
