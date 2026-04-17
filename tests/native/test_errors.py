"""Tests for EchelonError hierarchy and error catalog."""

import pytest

from echolon.native.validation.errors import (
    EchelonError,
    ValidationError,
    ConfigError,
    StrategyStructureError,
    IndicatorError,
    ParameterError,
    DataError,
)


def test_echolon_error_has_required_fields():
    err = EchelonError(
        code="VAL-001",
        what="Missing required field",
        why="Downstream code cannot proceed",
        fix="Add the field",
        context={"file": "entry.py"},
        docs_url="https://echolon.dev/docs/errors/VAL-001",
    )
    assert err.code == "VAL-001"
    assert err.what == "Missing required field"
    assert err.context == {"file": "entry.py"}


def test_echolon_error_str_includes_all_parts():
    err = EchelonError(
        code="VAL-001", what="Missing field", why="Need it", fix="Add it",
        context={"key": "value"},
        docs_url="https://echolon.dev/docs/errors/VAL-001",
    )
    s = str(err)
    assert "[VAL-001]" in s
    assert "Missing field" in s
    assert "Need it" in s
    assert "Add it" in s
    assert "key" in s


def test_echolon_error_is_exception():
    assert issubclass(EchelonError, Exception)


def test_subclasses_are_echolon_errors():
    for cls in [ValidationError, ConfigError, StrategyStructureError,
                IndicatorError, ParameterError, DataError]:
        assert issubclass(cls, EchelonError)


def test_subclass_can_be_raised_and_caught():
    with pytest.raises(ValidationError) as exc_info:
        raise ValidationError(
            code="VAL-001", what="test", why="test", fix="test",
            context={}, docs_url="https://example.com",
        )
    assert exc_info.value.code == "VAL-001"


def test_catching_echolon_error_catches_all_subclasses():
    try:
        raise IndicatorError(code="IND-001", what="x", why="y", fix="z", context={}, docs_url="u")
    except EchelonError as e:
        assert e.code == "IND-001"


from echolon.native.validation.errors import (
    ERROR_CATALOG,
    raise_error,
)


def test_catalog_has_required_entries():
    required = [
        "VAL-001", "VAL-002", "VAL-003",
        "CFG-001", "CFG-002",
        "STR-001", "STR-002", "STR-003",
        "IND-001", "IND-002",
        "PRM-001", "PRM-002",
        "DAT-001",
    ]
    for code in required:
        assert code in ERROR_CATALOG, f"Missing error code: {code}"


def test_catalog_entry_has_required_fields():
    entry = ERROR_CATALOG["VAL-001"]
    assert "class" in entry
    assert "what" in entry
    assert "why" in entry
    assert "fix_template" in entry
    assert issubclass(entry["class"], EchelonError)


def test_raise_error_raises_correct_subclass():
    with pytest.raises(ValidationError) as exc_info:
        raise_error("VAL-001", file="entry.py", method="generate_signal", missing=["type"])
    assert exc_info.value.code == "VAL-001"
    assert exc_info.value.context["file"] == "entry.py"


def test_raise_error_sets_docs_url():
    with pytest.raises(EchelonError) as exc_info:
        raise_error("VAL-001", file="x", method="y", missing=[])
    assert "https://echolon.dev/docs/errors/VAL-001" in exc_info.value.docs_url


def test_raise_error_unknown_code_raises_keyerror():
    with pytest.raises(KeyError):
        raise_error("BOGUS-999")


def test_raise_error_formats_fix_template():
    with pytest.raises(EchelonError) as exc_info:
        raise_error("IND-001", code_name="ATR_14", json_name="atr_14", file="entry.py")
    assert "ATR_14" in exc_info.value.fix or "atr_14" in exc_info.value.fix
