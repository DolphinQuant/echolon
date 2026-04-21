"""JSON-lines logging handler + per-module DEBUG gating.

Opt-in via env vars:
- ``ECHOLON_LOG_JSON=1`` emits JSON lines instead of free-form text.
- ``ECHOLON_DEBUG_MODULES=echolon.backtest.engine.hooks.*,echolon.indicators.*``
  enables DEBUG level on matched logger names (fnmatch-style patterns).

Call ``install_structured_logging()`` once at CLI/application startup to honour
the env vars; library modules never do this themselves.
"""
from __future__ import annotations

import fnmatch
import json
import logging
import os
import sys
import traceback
from datetime import datetime, timezone
from typing import Optional, TextIO


class _JsonFormatter(logging.Formatter):
    """logging.Formatter that emits one JSON object per line (JSONL)."""

    # Standard LogRecord attributes we don't re-serialize as "extras"
    _STD_ATTRS = frozenset({
        "args", "msg", "message", "name", "levelname", "levelno",
        "pathname", "filename", "module", "exc_info", "exc_text",
        "stack_info", "lineno", "funcName", "created", "msecs",
        "relativeCreated", "thread", "threadName", "processName",
        "process", "taskName",  # taskName is Python 3.12+
    })

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "module": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exc_info"] = "".join(traceback.format_exception(*record.exc_info)).strip()

        # Extra attrs passed via logger.xxx(..., extra={...})
        for key, value in record.__dict__.items():
            if key in self._STD_ATTRS or key.startswith("_"):
                continue
            try:
                json.dumps(value)
                payload[key] = value
            except (TypeError, ValueError):
                payload[key] = repr(value)

        return json.dumps(payload)


def _make_json_handler(stream: Optional[TextIO] = None) -> logging.Handler:
    """Build a StreamHandler configured with _JsonFormatter.

    Args:
        stream: Output stream (default sys.stderr). Useful for tests to
            capture output to a StringIO.
    """
    handler = logging.StreamHandler(stream if stream is not None else sys.stderr)
    handler.setFormatter(_JsonFormatter())
    return handler


def _configure_module_debug(patterns: list[str]) -> None:
    """Enable DEBUG level on every existing logger whose name matches any pattern."""
    for name in list(logging.root.manager.loggerDict):
        for pat in patterns:
            if fnmatch.fnmatch(name, pat):
                logging.getLogger(name).setLevel(logging.DEBUG)
                break


def install_structured_logging() -> None:
    """Honour ECHOLON_LOG_JSON and ECHOLON_DEBUG_MODULES env vars.

    Idempotent: calling multiple times is safe (doesn't double-install handlers).
    """
    root = logging.getLogger()

    if os.getenv("ECHOLON_LOG_JSON", "").lower() in ("1", "true", "yes"):
        already_installed = any(
            isinstance(h.formatter, _JsonFormatter) for h in root.handlers
        )
        if not already_installed:
            # Remove existing handlers so output is purely JSON-lines
            for existing in list(root.handlers):
                root.removeHandler(existing)
            root.addHandler(_make_json_handler())

    modules_env = os.getenv("ECHOLON_DEBUG_MODULES", "").strip()
    if modules_env:
        patterns = [p.strip() for p in modules_env.split(",") if p.strip()]
        _configure_module_debug(patterns)
