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
