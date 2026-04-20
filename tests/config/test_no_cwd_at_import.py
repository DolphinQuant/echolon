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


def test_project_root_module_attribute_is_deprecated_shim():
    """Back-compat: accessing PROJECT_ROOT still works but emits DeprecationWarning
    and resolves lazily (not bound at import time)."""
    import importlib
    import warnings

    # Force a fresh import so __getattr__ hook is freshly evaluated.
    import sys
    for name in list(sys.modules):
        if name.startswith("echolon.config.settings"):
            del sys.modules[name]

    mod = importlib.import_module("echolon.config.settings")

    # Access triggers the deprecation warning and lazy resolution.
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        value = mod.PROJECT_ROOT
        deprecation_warnings = [x for x in w if issubclass(x.category, DeprecationWarning)]

    assert isinstance(value, Path)
    assert value.is_absolute()
    assert value == mod.get_project_root(), \
        "PROJECT_ROOT should resolve to the same path as get_project_root()"
    assert deprecation_warnings, "PROJECT_ROOT access must emit DeprecationWarning"
    assert any("get_project_root" in str(x.message) for x in deprecation_warnings), \
        "DeprecationWarning must point callers at get_project_root()"
