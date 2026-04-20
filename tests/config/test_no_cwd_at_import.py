"""Regression: echolon.config.settings.get_project_root() resolves cwd at call
time, not at import time."""
import sys
from pathlib import Path


def test_get_project_root_reflects_cwd_changes_after_import(tmp_path, monkeypatch):
    """After importing settings, changing cwd must be visible via
    get_project_root() — the resolver re-reads the env / cwd on every call."""
    # Force a fresh import.
    for name in list(sys.modules):
        if name.startswith("echolon.config.settings"):
            del sys.modules[name]

    # Import from cwd A.
    monkeypatch.delenv("ECHOLON_PROJECT_ROOT", raising=False)
    monkeypatch.chdir(tmp_path)

    from echolon.config.settings import get_project_root
    assert get_project_root() == tmp_path.resolve()

    # Change cwd to a different location; get_project_root must reflect it.
    other = tmp_path.parent
    monkeypatch.chdir(other)
    assert get_project_root() == other.resolve()


def test_project_root_module_attribute_still_exists():
    """Back-compat: PROJECT_ROOT is still importable for callers that haven't
    migrated to get_project_root()."""
    import importlib
    mod = importlib.import_module("echolon.config.settings")
    assert hasattr(mod, "PROJECT_ROOT")
    assert isinstance(mod.PROJECT_ROOT, Path)
