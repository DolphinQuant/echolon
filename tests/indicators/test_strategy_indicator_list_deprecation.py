"""Phase A3 — StrategyIndicatorList becomes a deprecation-warning shim over IndicatorList.

Legacy 4-section payloads still validate (auto-translated), but each validation
emits a DeprecationWarning. Flat-dict payloads validate without warning.
"""
import warnings

import pytest
from pydantic import ValidationError

from echolon.strategy.schemas import StrategyIndicatorList


def test_legacy_4section_payload_validates_with_deprecation_warning():
    payload = {
        "indicators_with_lookback": {"RSI": [14, 28]},
        "indicators_without_lookback": ["obv"],
        "indicators_with_special_params": ["macd_line"],
    }
    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter("always")
        StrategyIndicatorList.model_validate(payload)
    dep_warnings = [w for w in captured if issubclass(w.category, DeprecationWarning)]
    assert len(dep_warnings) >= 1, f"Expected DeprecationWarning, got {captured}"
    assert any("4-section" in str(w.message) or "flat-dict" in str(w.message) for w in dep_warnings)


def test_flat_dict_payload_validates_without_warning():
    payload = {"rsi": {"timeperiod": [14, 28]}, "obv": {}}
    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter("always")
        StrategyIndicatorList.model_validate(payload)
    dep_warnings = [w for w in captured if issubclass(w.category, DeprecationWarning)]
    assert dep_warnings == [], f"Flat-dict must not trigger deprecation, got {dep_warnings}"


def test_legacy_4section_with_unknown_name_still_raises():
    """Translation preserves catalog validation — fake names fail."""
    payload = {
        "indicators_with_lookback": {"FAKE_INDICATOR": [5, 10]},
        "indicators_without_lookback": [],
        "indicators_with_special_params": [],
    }
    with pytest.raises(ValidationError) as excinfo:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            StrategyIndicatorList.model_validate(payload)
    assert "FAKE_INDICATOR" in str(excinfo.value) or "fake_indicator" in str(excinfo.value).lower()


def test_legacy_4section_system_provided_indicators_is_dropped():
    """system_provided_indicators is informational — stripped during translation."""
    payload = {
        "indicators_with_lookback": {"RSI": [14, 28]},
        "indicators_without_lookback": [],
        "indicators_with_special_params": [],
        "system_provided_indicators": {"bar_of_day": "Current bar index"},
    }
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        # Must not raise — bar_of_day is not in the interday catalog but the
        # translator drops system_provided_indicators entirely.
        StrategyIndicatorList.model_validate(payload)


def test_model_validate_json_works_on_legacy_string():
    """The primary tool entry point (model_validate_json) must handle legacy payloads."""
    import json
    payload_str = json.dumps({
        "indicators_with_lookback": {"RSI": [14, 28]},
        "indicators_without_lookback": [],
        "indicators_with_special_params": [],
    })
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        StrategyIndicatorList.model_validate_json(payload_str)


def test_flat_dict_model_validate_json_works():
    """Flat-dict JSON strings validate through the same entry point."""
    import json
    StrategyIndicatorList.model_validate_json(json.dumps({"rsi": {"timeperiod": 14}}))
