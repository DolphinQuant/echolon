#!/usr/bin/env python3
"""Post-decision script for KEEP/REVERT workflow.

Executed by the validator/exploitate agent AFTER making a KEEP/REVERT decision.

Paths default to ``PathsConfig.from_env()`` (i.e. ``$ECHOLON_PROJECT_ROOT``). Pass
``--strategy-dir`` / ``--backtest-dir`` to override.

Usage:
    python post_decision.py --keep
    python post_decision.py --revert
    python post_decision.py --keep --strategy-dir /path/to/code --backtest-dir /path/to/backtest

For ``--keep``:
    1. Verify ``backtest_results.json`` ``run_context == "best_trial"`` (not "debug").
    2. Delete all ``.backup`` files and the ``<backtest_dir>.backup/`` folder.
    3. Retain the revised scripts and new backtest results.

For ``--revert``:
    1. Restore all ``.backup`` files to original names.
    2. Restore ``<backtest_dir>.backup/`` to ``<backtest_dir>/``.
    3. Discard the failed changes.
"""
import argparse
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

from echolon.config.paths_config import PathsConfig

BACKUPABLE_FILES = [
    "entry.py",
    "exit.py",
    "risk.py",
    "sizer.py",
    "strategy.py",
    "strategy_params.py",
    "strategy_indicator_list.json",
    "selected_robust_trial.json",
]


def resolve_paths(strategy_dir: str | None, backtest_dir: str | None) -> tuple[Path, Path]:
    if strategy_dir is not None and backtest_dir is not None:
        return Path(strategy_dir).resolve(), Path(backtest_dir).resolve()
    paths = PathsConfig.from_env()
    return (
        Path(strategy_dir).resolve() if strategy_dir else paths.strategy_code_dir,
        Path(backtest_dir).resolve() if backtest_dir else paths.backtest_results_dir,
    )


def verify_run_context(backtest_dir: Path) -> tuple[bool, str | None, str | None]:
    """Verify backtest was run with ``run_context="best_trial"``.

    Returns ``(is_valid, run_context_value, error_message)``.
    """
    results_path = backtest_dir / "backtest_results.json"

    if not results_path.exists():
        return False, None, f"backtest_results.json not found at {results_path}"

    with open(results_path, "r") as f:
        results = json.load(f)

    run_context = results.get("run_context")

    if run_context == "debug":
        return False, run_context, "run_context is 'debug' - cannot KEEP debug results"
    if run_context != "best_trial":
        return False, run_context, (
            f"run_context is '{run_context}' - expected 'best_trial'"
        )
    return True, run_context, None


def execute_keep(strategy_dir: Path, backtest_dir: Path) -> dict:
    result = {
        "decision": "KEEP",
        "success": True,
        "strategy_dir": str(strategy_dir),
        "backtest_dir": str(backtest_dir),
        "files_deleted": [],
        "folders_deleted": [],
        "timestamp": datetime.now().isoformat(),
        "errors": [],
    }

    is_valid, run_context, error_msg = verify_run_context(backtest_dir)
    result["run_context"] = run_context

    if not is_valid:
        result["success"] = False
        result["errors"].append(error_msg)
        print(f"ERROR: {error_msg}")
        return result

    print(f"Verified run_context: {run_context}")

    for filename in BACKUPABLE_FILES:
        backup_path = strategy_dir / f"{filename}.backup"
        if backup_path.exists():
            backup_path.unlink()
            result["files_deleted"].append(str(backup_path))
            print(f"Deleted: {filename}.backup")

    backtest_backup_path = backtest_dir.parent / f"{backtest_dir.name}.backup"
    if backtest_backup_path.exists():
        shutil.rmtree(backtest_backup_path)
        result["folders_deleted"].append(str(backtest_backup_path))
        print(f"Deleted: {backtest_backup_path.name}/")

    print("KEEP completed: New files retained, backups deleted")
    return result


def execute_revert(strategy_dir: Path, backtest_dir: Path) -> dict:
    result = {
        "decision": "REVERT",
        "success": True,
        "strategy_dir": str(strategy_dir),
        "backtest_dir": str(backtest_dir),
        "files_restored": [],
        "backtest_restored": False,
        "timestamp": datetime.now().isoformat(),
        "errors": [],
    }

    for filename in BACKUPABLE_FILES:
        backup_path = strategy_dir / f"{filename}.backup"
        target_path = strategy_dir / filename

        if backup_path.exists():
            shutil.copy2(backup_path, target_path)
            backup_path.unlink()
            result["files_restored"].append(filename)
            print(f"Restored: {filename}.backup -> {filename}")

    backtest_backup_path = backtest_dir.parent / f"{backtest_dir.name}.backup"
    if backtest_backup_path.exists():
        if backtest_dir.exists():
            shutil.rmtree(backtest_dir)
        shutil.move(str(backtest_backup_path), str(backtest_dir))
        result["backtest_restored"] = True
        print(f"Restored: {backtest_backup_path.name}/ -> {backtest_dir.name}/")
    else:
        error_msg = f"{backtest_backup_path.name}/ not found - cannot restore"
        result["errors"].append(error_msg)
        result["success"] = False
        print(f"ERROR: {error_msg}")

    if result["success"]:
        print("REVERT completed: Backups restored, new files discarded")
    return result


def main() -> int:
    from echolon._internal.structured_logging import install_structured_logging
    install_structured_logging()

    parser = argparse.ArgumentParser(
        description="Post-decision handler for KEEP/REVERT workflow."
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--keep", action="store_true",
                       help="KEEP new files, delete backups")
    group.add_argument("--revert", action="store_true",
                       help="REVERT to backups, discard new files")
    parser.add_argument("--strategy-dir", default=None,
                        help="Directory containing strategy code files. "
                             "Defaults to PathsConfig.from_env().strategy_code_dir.")
    parser.add_argument("--backtest-dir", default=None,
                        help="Directory containing backtest results. "
                             "Defaults to PathsConfig.from_env().backtest_results_dir.")
    args = parser.parse_args()

    strategy_dir, backtest_dir = resolve_paths(args.strategy_dir, args.backtest_dir)

    if args.keep:
        result = execute_keep(strategy_dir, backtest_dir)
    else:
        result = execute_revert(strategy_dir, backtest_dir)

    print(json.dumps(result, indent=2, default=str))
    return 0 if result["success"] else 1


if __name__ == "__main__":
    sys.exit(main())
