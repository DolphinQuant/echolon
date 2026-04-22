#!/usr/bin/env python3
"""
CLI script for creating validation backup.

Creates backup of:
- All platform-agnostic strategy files (*.backup)
- Entire backtest results folder (backtest.backup/)

Only ONE backup exists at a time. Running this script overwrites any existing backup.

Usage:
    python backup.py

Output:
    JSON with success status and backup details
"""
import sys
import json
import shutil
from pathlib import Path
from datetime import datetime

# Compute paths relative to script location (no config import needed)
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent.parent.parent  # .claude/skills/validation-backup/scripts -> root
WORKSPACE_DIR = PROJECT_ROOT / "workspace"

# Directory constants
PLATFORM_AGNOSTIC_DIR = PROJECT_ROOT / "modules" / "quant_engine" / "strategy" / "platform_agnostic"
BACKTEST_RESULTS_DIR = WORKSPACE_DIR / "current" / "backtest"
REFINE_DIR = WORKSPACE_DIR / "current"

# Files that can be backed up in platform_agnostic
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


def create_backup():
    """
    Create backup of ALL platform-agnostic files and backtest results folder.

    Uses simple .backup suffix. Only one backup exists at a time.

    Returns:
        Dict with success status and backup details
    """
    result = {
        "success": True,
        "file_backups": {},
        "backtest_backup": None,
        "timestamp": datetime.now().isoformat(),
        "errors": []
    }

    # Backup ALL platform-agnostic files
    for filename in BACKUPABLE_FILES:
        source_path = PLATFORM_AGNOSTIC_DIR / filename
        backup_path = PLATFORM_AGNOSTIC_DIR / f"{filename}.backup"

        if source_path.exists():
            try:
                # Overwrite existing backup if present
                shutil.copy2(source_path, backup_path)
                result["file_backups"][filename] = str(backup_path)
                print(f"Backed up: {filename} -> {filename}.backup")
            except Exception as e:
                error_msg = f"Failed to backup {filename}: {e}"
                result["errors"].append(error_msg)
                result["success"] = False
                print(f"ERROR: {error_msg}")

    # Backup backtest results folder
    backtest_backup_path = REFINE_DIR / "backtest.backup"

    if BACKTEST_RESULTS_DIR.exists():
        try:
            # Remove existing backup if present
            if backtest_backup_path.exists():
                shutil.rmtree(backtest_backup_path)

            # Create new backup
            shutil.copytree(BACKTEST_RESULTS_DIR, backtest_backup_path)
            result["backtest_backup"] = str(backtest_backup_path)
            print(f"Backed up: backtest/ -> backtest.backup/")
        except Exception as e:
            error_msg = f"Failed to backup backtest folder: {e}"
            result["errors"].append(error_msg)
            result["success"] = False
            print(f"ERROR: {error_msg}")
    else:
        print(f"Warning: Backtest folder does not exist: {BACKTEST_RESULTS_DIR}")

    return result


def main():
    """Create validation backup and output result as JSON."""
    result = create_backup()
    print(json.dumps(result, indent=2, default=str))
    return 0 if result["success"] else 1


if __name__ == "__main__":
    sys.exit(main())
