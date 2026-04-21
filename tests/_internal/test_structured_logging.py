"""JSON-lines logging handler: activates via env var, emits structured events."""
import io
import json
import logging

import pytest


def test_make_json_handler_emits_jsonl():
    from echolon._internal import structured_logging

    buf = io.StringIO()
    handler = structured_logging._make_json_handler(stream=buf)

    logger = logging.getLogger("echolon.test.structured_a")
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    try:
        logger.info("hello")
    finally:
        logger.removeHandler(handler)

    lines = [line for line in buf.getvalue().splitlines() if line]
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["level"] == "INFO"
    assert record["module"] == "echolon.test.structured_a"
    assert record["message"] == "hello"
    assert "ts" in record


def test_json_handler_captures_exc_info():
    from echolon._internal import structured_logging
    from echolon.errors import raise_error

    buf = io.StringIO()
    handler = structured_logging._make_json_handler(stream=buf)
    logger = logging.getLogger("echolon.test.structured_b")
    logger.addHandler(handler)
    logger.setLevel(logging.ERROR)

    try:
        try:
            raise_error("DAT-001", path="/nonexistent.csv", field="market_data_dir")
        except Exception:
            logger.error("failure", exc_info=True)
    finally:
        logger.removeHandler(handler)

    lines = [line for line in buf.getvalue().splitlines() if line]
    record = json.loads(lines[0])
    assert "exc_info" in record
    # The EchelonError's code should appear in the formatted traceback
    assert "DAT-001" in record["exc_info"]


def test_json_handler_preserves_extra_fields():
    """When a caller passes `extra={...}`, those fields appear in the JSON record."""
    from echolon._internal import structured_logging

    buf = io.StringIO()
    handler = structured_logging._make_json_handler(stream=buf)
    logger = logging.getLogger("echolon.test.structured_c")
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

    try:
        logger.info("hello", extra={"slot_id": "alpha-7"})
    finally:
        logger.removeHandler(handler)

    lines = [line for line in buf.getvalue().splitlines() if line]
    record = json.loads(lines[0])
    assert record["slot_id"] == "alpha-7"


def test_json_handler_stringifies_non_serializable_extras():
    """Non-JSON-serializable extras fall back to repr(value)."""
    from echolon._internal import structured_logging

    class NotSerializable:
        def __repr__(self):
            return "<NotSerializable>"

    buf = io.StringIO()
    handler = structured_logging._make_json_handler(stream=buf)
    logger = logging.getLogger("echolon.test.structured_d")
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

    try:
        logger.info("hello", extra={"obj": NotSerializable()})
    finally:
        logger.removeHandler(handler)

    lines = [line for line in buf.getvalue().splitlines() if line]
    record = json.loads(lines[0])
    assert record["obj"] == "<NotSerializable>"


def test_install_is_idempotent(monkeypatch):
    """install_structured_logging() must not double-install handlers."""
    monkeypatch.setenv("ECHOLON_LOG_JSON", "1")
    from echolon._internal.structured_logging import install_structured_logging, _JsonFormatter

    root = logging.getLogger()
    # Clean state for the test
    for h in list(root.handlers):
        root.removeHandler(h)

    try:
        install_structured_logging()
        install_structured_logging()
        json_handlers = [h for h in root.handlers if isinstance(h.formatter, _JsonFormatter)]
        assert len(json_handlers) == 1
    finally:
        # Reset so other tests aren't affected
        for h in list(root.handlers):
            root.removeHandler(h)


def test_debug_modules_env_var_raises_level(monkeypatch):
    """ECHOLON_DEBUG_MODULES turns on DEBUG level for matching logger names."""
    # Make sure the target logger exists before install is called so _configure_module_debug finds it.
    logging.getLogger("echolon.backtest.engine.hooks.contract_aware.broker")
    monkeypatch.delenv("ECHOLON_LOG_JSON", raising=False)
    monkeypatch.setenv("ECHOLON_DEBUG_MODULES", "echolon.backtest.engine.hooks.*")

    from echolon._internal.structured_logging import install_structured_logging
    install_structured_logging()

    target = logging.getLogger("echolon.backtest.engine.hooks.contract_aware.broker")
    assert target.level == logging.DEBUG
