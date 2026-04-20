"""ECHOLON_PROJECT_ROOT resolver.

This module is deliberately minimal. Library callers should construct
``echolon.config.paths_config.PathsConfig`` explicitly at their entry points;
``get_project_root()`` here is the fallback used only when a caller supplies
no paths at all.

``PROJECT_ROOT`` remains as a module attribute (eager at import time) for
backwards compatibility with callers that historically imported it. New code
should prefer ``get_project_root()`` — the function re-reads the env var on
every call, so env-var changes after import are honored.
"""
import os
from pathlib import Path


def get_project_root() -> Path:
    """Resolve ECHOLON_PROJECT_ROOT (defaults to cwd) at call time."""
    return Path(os.getenv("ECHOLON_PROJECT_ROOT", Path.cwd())).absolute()


# Module-level eager resolution. Retained for back-compat with callers that
# imported PROJECT_ROOT directly; new code should call get_project_root().
PROJECT_ROOT = get_project_root()
