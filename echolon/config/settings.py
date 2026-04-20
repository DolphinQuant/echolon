"""ECHOLON_PROJECT_ROOT resolver.

This module is deliberately minimal. Library callers should construct
``echolon.config.paths_config.PathsConfig`` explicitly at their entry points;
``get_project_root()`` here is the fallback used only when a caller supplies
no paths at all.
"""
import os
from pathlib import Path


def get_project_root() -> Path:
    """Resolve ECHOLON_PROJECT_ROOT (defaults to cwd) at call time."""
    return Path(os.getenv("ECHOLON_PROJECT_ROOT") or Path.cwd()).absolute()
