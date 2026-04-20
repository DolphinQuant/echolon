"""ECHOLON_PROJECT_ROOT resolver.

This module is deliberately minimal. Library callers should construct
``echolon.config.paths_config.PathsConfig`` explicitly at their entry points;
``get_project_root()`` here is the fallback used only when a caller supplies
no paths at all.

``PROJECT_ROOT`` is retained as a module attribute for back-compat but is now
lazy (resolved on attribute access, not import) AND emits a DeprecationWarning
on each access. Migrate to ``get_project_root()`` — the function re-reads the
env var on every call, so env-var changes after import are honored and the
access is no longer a deprecation-warned path. The ``PROJECT_ROOT`` attribute
will be removed in a future release once all known callers have migrated.
"""
import os
import warnings
from pathlib import Path


def get_project_root() -> Path:
    """Resolve ECHOLON_PROJECT_ROOT (defaults to cwd) at call time."""
    return Path(os.getenv("ECHOLON_PROJECT_ROOT") or Path.cwd()).absolute()


def __getattr__(name: str) -> Path:
    """Lazy resolution of deprecated module attributes."""
    if name == "PROJECT_ROOT":
        warnings.warn(
            "echolon.config.settings.PROJECT_ROOT is deprecated and will be "
            "removed in a future release. Use "
            "echolon.config.settings.get_project_root() instead, which re-reads "
            "the env var on each call and does not bind cwd at import time.",
            DeprecationWarning,
            stacklevel=2,
        )
        return get_project_root()
    raise AttributeError(f"module 'echolon.config.settings' has no attribute {name!r}")
