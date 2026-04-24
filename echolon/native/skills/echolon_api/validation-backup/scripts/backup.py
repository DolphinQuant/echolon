#!/usr/bin/env python3
"""CLI script for creating a validation backup.

Creates backup of:
- All platform-agnostic strategy files in ``strategy_code_dir`` (``<file>.backup``)
- Entire backtest results folder (``<backtest_dir>.backup``)

Only ONE backup exists at a time. Running this script overwrites any existing
backup.

Paths default to ``PathsConfig.from_env()`` (i.e. ``$ECHOLON_PROJECT_ROOT``). Pass
``--strategy-dir`` / ``--backtest-dir`` to override either path — useful for
tests and workspace layouts that don't match the default.

Usage:
    python backup.py
    python backup.py --strategy-dir /path/to/code --backtest-dir /path/to/backtest

Output:
    JSON with success status and backup details.
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
    """Resolve ``strategy_dir`` / ``backtest_dir``, defaulting to ``PathsConfig.from_env()``."""
    if strategy_dir is not None and backtest_dir is not None:
        return Path(strategy_dir).resolve(), Path(backtest_dir).resolve()
    paths = PathsConfig.from_env()
    return (
        Path(strategy_dir).resolve() if strategy_dir else paths.strategy_code_dir,
        Path(backtest_dir).resolve() if backtest_dir else paths.backtest_results_dir,
    )


def create_backup(strategy_dir: Path, backtest_dir: Path) -> dict:
    """Create backup of all strategy files and the backtest results folder."""
    result = {
        "success": True,
        "strategy_dir": str(strategy_dir),
        "backtest_dir": str(backtest_dir),
        "file_backups": {},
        "backtest_backup": None,
        "timestamp": datetime.now().isoformat(),
        "errors": [],
    }

    for filename in BACKUPABLE_FILES:
        source_path = strategy_dir / filename
        backup_path = strategy_dir / f"{filename}.backup"

        if source_path.exists():
            shutil.copy2(source_path, backup_path)
            result["file_backups"][filename] = str(backup_path)
            print(f"Backed up: {filename} -> {filename}.backup")

    backtest_backup_path = backtest_dir.parent / f"{backtest_dir.name}.backup"
    if backtest_dir.exists():
        if backtest_backup_path.exists():
            shutil.rmtree(backtest_backup_path)
        shutil.copytree(backtest_dir, backtest_backup_path)
        result["backtest_backup"] = str(backtest_backup_path)
        print(f"Backed up: {backtest_dir.name}/ -> {backtest_backup_path.name}/")
    else:
        print(f"Warning: Backtest folder does not exist: {backtest_dir}")

    return result


def main() -> int:
    from echolon._internal.structured_logging import install_structured_logging
    install_structured_logging()

    parser = argparse.ArgumentParser(description="Create validation backup.")
    parser.add_argument("--strategy-dir", default=None,
                        help="Directory containing strategy code files. "
                             "Defaults to PathsConfig.from_env().strategy_code_dir.")
    parser.add_argument("--backtest-dir", default=None,
                        help="Directory containing backtest results. "
                             "Defaults to PathsConfig.from_env().backtest_results_dir.")
    args = parser.parse_args()

    strategy_dir, backtest_dir = resolve_paths(args.strategy_dir, args.backtest_dir)
    result = create_backup(strategy_dir, backtest_dir)
    print(json.dumps(result, indent=2, default=str))
    return 0 if result["success"] else 1


if __name__ == "__main__":
    sys.exit(main())
