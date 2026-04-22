"""Tests for echolon programmatic APIs (Phase 1 workstream C)."""
import pytest
from pathlib import Path


def test_validate_strategy_importable():
    from echolon.native.validation import validate_strategy
    assert callable(validate_strategy)


def test_validate_strategy_returns_result(tmp_path):
    from echolon.native.validation import validate_strategy
    # Point at a template directory that should validate OK (or an empty dir that fails clean)
    result = validate_strategy(tmp_path)
    # Accept either VALID or a ValidationResult with errors — just that it returns something structured
    assert hasattr(result, "status") or hasattr(result, "errors") or isinstance(result, dict)


def test_get_error_doc_returns_doc():
    from echolon.native.errors import get_error_doc
    doc = get_error_doc("VAL-001")
    assert doc is not None
    # Doc should have at least 'what' or be parseable from docs/errors/VAL-001.md
    assert hasattr(doc, "what") or "what" in str(doc).lower() or isinstance(doc, dict)


def test_get_error_doc_raises_on_unknown_code():
    from echolon.native.errors import get_error_doc
    with pytest.raises((KeyError, ValueError, FileNotFoundError)):
        get_error_doc("ZZZ-999")
