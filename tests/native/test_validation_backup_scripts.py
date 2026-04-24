"""Tests for validation-backup scripts (backup.py + post_decision.py).

Exercises the --strategy-dir / --backtest-dir CLI surface with a scratch
workspace so the tests are independent of PathsConfig.from_env(). The scripts
live under ``native/skills/echolon_api/validation-backup/scripts/`` — the
directory dash blocks regular imports, so they are loaded via importlib.
"""
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

import echolon

_SCRIPTS_DIR = Path(echolon.__file__).parent / "native" / "skills" / "echolon_api" / "validation-backup" / "scripts"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(
        f"_test_{name}", _SCRIPTS_DIR / f"{name}.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


backup_module = _load("backup")
post_decision_module = _load("post_decision")


BACKUPABLE_FILES = [
    "entry.py", "exit.py", "risk.py", "sizer.py", "strategy.py",
    "strategy_params.py", "strategy_indicator_list.json",
    "selected_robust_trial.json",
]


@pytest.fixture
def workspace(tmp_path: Path) -> tuple[Path, Path]:
    """Scratch ``(strategy_dir, backtest_dir)`` with stub files."""
    strategy_dir = tmp_path / "code"
    backtest_dir = tmp_path / "current" / "backtest"
    strategy_dir.mkdir()
    backtest_dir.mkdir(parents=True)

    for filename in BACKUPABLE_FILES:
        (strategy_dir / filename).write_text(f"# original {filename}\n")

    (backtest_dir / "backtest_results.json").write_text(
        json.dumps({"run_context": "best_trial", "metric": 1.0})
    )
    return strategy_dir, backtest_dir


def test_backup_creates_sidecar_files(workspace):
    strategy_dir, backtest_dir = workspace
    result = backup_module.create_backup(strategy_dir, backtest_dir)

    assert result["success"] is True
    for filename in BACKUPABLE_FILES:
        assert (strategy_dir / f"{filename}.backup").exists(), filename
    assert (backtest_dir.parent / f"{backtest_dir.name}.backup").exists()
    assert (backtest_dir.parent / f"{backtest_dir.name}.backup" /
            "backtest_results.json").exists()


def test_backup_overwrites_previous_backup(workspace):
    strategy_dir, backtest_dir = workspace
    backup_module.create_backup(strategy_dir, backtest_dir)

    (strategy_dir / "entry.py").write_text("# revised\n")
    backup_module.create_backup(strategy_dir, backtest_dir)

    assert (strategy_dir / "entry.py.backup").read_text() == "# revised\n"


def test_keep_requires_best_trial_run_context(workspace):
    strategy_dir, backtest_dir = workspace
    backup_module.create_backup(strategy_dir, backtest_dir)

    (backtest_dir / "backtest_results.json").write_text(
        json.dumps({"run_context": "debug"})
    )
    result = post_decision_module.execute_keep(strategy_dir, backtest_dir)

    assert result["success"] is False
    assert "debug" in result["errors"][0]
    assert (strategy_dir / "entry.py.backup").exists(), (
        "KEEP should abort without deleting backups when run_context is debug"
    )


def test_keep_removes_backups_when_valid(workspace):
    strategy_dir, backtest_dir = workspace
    backup_module.create_backup(strategy_dir, backtest_dir)

    result = post_decision_module.execute_keep(strategy_dir, backtest_dir)

    assert result["success"] is True
    for filename in BACKUPABLE_FILES:
        assert not (strategy_dir / f"{filename}.backup").exists()
    assert not (backtest_dir.parent / f"{backtest_dir.name}.backup").exists()


def test_revert_restores_code_and_backtest(workspace):
    strategy_dir, backtest_dir = workspace
    backup_module.create_backup(strategy_dir, backtest_dir)

    (strategy_dir / "entry.py").write_text("# broken revision\n")
    (backtest_dir / "backtest_results.json").write_text(
        json.dumps({"run_context": "debug"})
    )

    result = post_decision_module.execute_revert(strategy_dir, backtest_dir)

    assert result["success"] is True
    assert (strategy_dir / "entry.py").read_text() == "# original entry.py\n"
    payload = json.loads((backtest_dir / "backtest_results.json").read_text())
    assert payload["run_context"] == "best_trial"
    assert not (strategy_dir / "entry.py.backup").exists()


def test_cli_surface_runs_end_to_end(workspace):
    strategy_dir, backtest_dir = workspace

    rc = subprocess.run(
        [sys.executable, str(_SCRIPTS_DIR / "backup.py"),
         "--strategy-dir", str(strategy_dir),
         "--backtest-dir", str(backtest_dir)],
        check=True, capture_output=True, text=True,
    )
    assert "success" in rc.stdout

    rc = subprocess.run(
        [sys.executable, str(_SCRIPTS_DIR / "post_decision.py"), "--keep",
         "--strategy-dir", str(strategy_dir),
         "--backtest-dir", str(backtest_dir)],
        check=True, capture_output=True, text=True,
    )
    assert "KEEP" in rc.stdout
    for filename in BACKUPABLE_FILES:
        assert not (strategy_dir / f"{filename}.backup").exists()
