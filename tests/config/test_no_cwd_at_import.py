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


def test_project_root_module_attribute_is_removed():
    """PROJECT_ROOT is gone; accessing it raises AttributeError."""
    import importlib
    for name in list(sys.modules):
        if name.startswith("echolon.config.settings"):
            del sys.modules[name]

    mod = importlib.import_module("echolon.config.settings")
    try:
        _ = mod.PROJECT_ROOT
    except AttributeError:
        pass
    else:
        raise AssertionError("PROJECT_ROOT should be removed, but is still accessible")
