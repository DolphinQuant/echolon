"""Item 1 TDD: derived-column grammar in catalog.validate.

Written BEFORE the production change. Tests fail against the current catalog.py
which does not implement the fit-suffix or windowed-derived grammar.
"""
import pytest

from echolon.indicators import catalog
from echolon.indicators.registry import register_regime_classifier, KNOWN_REGIME_COLUMNS


# ---------------------------------------------------------------------------
# Grammar (a): {base}__fit{YYYYMMDD} — vintage-suffixed regime columns
# ---------------------------------------------------------------------------

def test_fit_suffix_regime_column_passes():
    """market_regime__fit20201231 is a valid vintage-suffixed regime column."""
    errors = catalog.validate({"market_regime__fit20201231": {}})
    assert errors == [], f"Expected no errors, got: {errors}"


def test_fit_suffix_session_phase_passes():
    """session_phase__fit20210101 is a valid vintage-suffixed session column."""
    errors = catalog.validate({"session_phase__fit20210101": {}})
    assert errors == [], f"Expected no errors, got: {errors}"


def test_fit_suffix_registered_classifier_passes():
    """A registered classifier base with a __fitYYYYMMDD suffix must pass."""
    # Register a stub classifier so is_registered_classifier returns True for it
    class _StubClassifier:
        name = "test_clf"

        def fit_classify(self, df, params):
            return df["close"] * 0

    stub = _StubClassifier()
    register_regime_classifier(stub)
    try:
        errors = catalog.validate({"test_clf__fit20200101": {}})
        assert errors == [], f"Expected no errors for registered classifier suffix, got: {errors}"
    finally:
        # Clean up: remove from registry if possible
        from echolon.indicators.registry.regime_classifiers import _CLASSIFIERS, _LOCK
        with _LOCK:
            _CLASSIFIERS.pop("test_clf", None)


def test_fit_suffix_invalid_token_fails():
    """market_regime__fitABCDEFGH should fail — suffix digits must be 8 numeric."""
    errors = catalog.validate({"market_regime__fitabcdefgh": {}})
    assert len(errors) >= 1, "Expected IND-004 because suffix is not 8 digits"


def test_fit_suffix_base_not_regime_fails():
    """rsi__fit20201231 must fail — rsi is not a regime column."""
    errors = catalog.validate({"rsi__fit20201231": {}})
    assert len(errors) >= 1, "Expected IND-004 because rsi is not a regime column"


# ---------------------------------------------------------------------------
# Grammar (b): {base}_pctl_{N} or {base}_z_{N} — windowed derived columns
# ---------------------------------------------------------------------------

def test_windowed_pctl_passes():
    """rsi_pctl_14 is a valid windowed-percentile derived column."""
    errors = catalog.validate({"rsi_pctl_14": {}})
    assert errors == [], f"Expected no errors, got: {errors}"


def test_windowed_z_passes():
    """obv_z_20 is a valid windowed-zscore derived column."""
    errors = catalog.validate({"obv_z_20": {}})
    assert errors == [], f"Expected no errors, got: {errors}"


def test_windowed_unknown_base_fails():
    """notanindicator_pctl_5 must fail — base is not in the catalog."""
    errors = catalog.validate({"notanindicator_pctl_5": {}})
    assert len(errors) >= 1, "Expected IND-004 because base is not in the catalog"


def test_windowed_non_int_suffix_fails():
    """rsi_pctl_abc must fail — suffix is not an integer."""
    errors = catalog.validate({"rsi_pctl_abc": {}})
    assert len(errors) >= 1, "Expected IND-004 because suffix 'abc' is not an integer"


# ---------------------------------------------------------------------------
# Regression: plain exact-match names still work
# ---------------------------------------------------------------------------

def test_exact_match_still_required_for_plain_names():
    """rsi (no suffix) still resolves directly from the catalog."""
    errors = catalog.validate({"rsi": {}})
    assert errors == [], f"Expected no errors for plain 'rsi', got: {errors}"
