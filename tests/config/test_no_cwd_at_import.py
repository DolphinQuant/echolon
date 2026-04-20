"""Regression: echolon.config.settings must not read cwd at import time.

This test is xfailed until Task 6, when settings.py is shrunk to only
``get_project_root()`` and the module-level ``PROJECT_ROOT`` constant is
removed. When that happens the xfail should flip to XPASS (strict) and the
marker can be dropped.
"""
import importlib
import sys
from pathlib import Path

import pytest


@pytest.mark.xfail(
    reason="PROJECT_ROOT still binds cwd at import — fixed in Task 6 when "
           "settings.py is shrunk to only get_project_root().",
    strict=True,
)
def test_settings_import_does_not_bind_cwd(tmp_path, monkeypatch):
    """Importing echolon.config.settings from a different cwd must not
    leak that cwd into module constants."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("ECHOLON_PROJECT_ROOT", raising=False)

    # Force a fresh import
    for name in list(sys.modules):
        if name.startswith("echolon.config.settings"):
            del sys.modules[name]

    mod = importlib.import_module("echolon.config.settings")

    # After Task 6 the constants are gone entirely; for now assert that
    # no module-level attribute equals tmp_path-rooted cwd.
    assert not hasattr(mod, "PROJECT_ROOT") or Path(mod.PROJECT_ROOT) != tmp_path.resolve()
