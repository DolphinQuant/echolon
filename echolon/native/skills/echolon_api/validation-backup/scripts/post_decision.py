#!/usr/bin/env python3
"""
Post-decision script for KEEP/REVERT workflow.

Must be executed by validator/exploitate agent AFTER making KEEP/REVERT decision.

Usage:
    python post_decision.py --keep     # Delete backups, keep new files
    python post_decision.py --revert   # Restore from backups, discard new files

For --keep:
    1. Verify backtest_results.json run_context is "best_trial" (not "debug")
    2. Delete all .backup files and backtest.backup/ folder
    3. Keep the revised scripts and new backtest results

For --revert:
    1. Restore all .backup files to original names
    2. Restore backtest.backup/ to backtest/
    3. Discard the failed changes
"""
import sys
import json
import shutil
import argparse
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

# Files that can be backed up
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


def verify_run_context():
    """
    Verify that backtest was run with run_context="best_trial".

    Returns:
        tuple: (is_valid, run_context_value, error_message)
    """
    results_path = BACKTEST_RESULTS_DIR / "backtest_results.json"

    if not results_path.exists():
        return False, None, f"backtest_results.json not found at {results_path}"

    with open(results_path, 'r') as f:
        results = json.load(f)

    run_context = results.get("run_context")

    if run_context == "debug":
        return False, run_context, "run_context is 'debug' - cannot KEEP debug results"

    if run_context != "best_trial":
        return False, run_context, f"run_context is '{run_context}' - expected 'best_trial'"

    return True, run_context, None


def execute_keep():
    """
    Execute KEEP decision: delete backups, retain new files.

    Returns:
        Dict with operation results
    """
    result = {
        "decision": "KEEP",
        "success": True,
        "files_deleted": [],
        "folders_deleted": [],
        "timestamp": datetime.now().isoformat(),
        "errors": []
    }

    # Step 1: Verify run_context
    is_valid, run_context, error_msg = verify_run_context()
    result["run_context"] = run_context

    if not is_valid:
        result["success"] = False
        result["errors"].append(error_msg)
        print(f"ERROR: {error_msg}")
        return result

    print(f"Verified run_context: {run_context}")

    # Step 2: Delete platform-agnostic backup files
    for filename in BACKUPABLE_FILES:
        backup_path = PLATFORM_AGNOSTIC_DIR / f"{filename}.backup"
        if backup_path.exists():
            try:
                backup_path.unlink()
                result["files_deleted"].append(str(backup_path))
                print(f"Deleted: {filename}.backup")
            except Exception as e:
                error_msg = f"Failed to delete {filename}.backup: {e}"
                result["errors"].append(error_msg)
                print(f"WARNING: {error_msg}")

    # Step 3: Delete backtest backup folder
    backtest_backup_path = REFINE_DIR / "backtest.backup"
    if backtest_backup_path.exists():
        try:
            shutil.rmtree(backtest_backup_path)
            result["folders_deleted"].append(str(backtest_backup_path))
            print(f"Deleted: backtest.backup/")
        except Exception as e:
            error_msg = f"Failed to delete backtest.backup: {e}"
            result["errors"].append(error_msg)
            print(f"WARNING: {error_msg}")

    print("KEEP completed: New files retained, backups deleted")
    return result


def execute_revert():
    """
    Execute REVERT decision: restore from backups, discard new files.

    Returns:
        Dict with operation results
    """
    result = {
        "decision": "REVERT",
        "success": True,
        "files_restored": [],
        "backtest_restored": False,
        "timestamp": datetime.now().isoformat(),
        "errors": []
    }

    # Step 1: Restore platform-agnostic files from backups
    for filename in BACKUPABLE_FILES:
        backup_path = PLATFORM_AGNOSTIC_DIR / f"{filename}.backup"
        target_path = PLATFORM_AGNOSTIC_DIR / filename

        if backup_path.exists():
            try:
                shutil.copy2(backup_path, target_path)
                backup_path.unlink()  # Remove backup after restoring
                result["files_restored"].append(filename)
                print(f"Restored: {filename}.backup -> {filename}")
            except Exception as e:
                error_msg = f"Failed to restore {filename}: {e}"
                result["errors"].append(error_msg)
                result["success"] = False
                print(f"ERROR: {error_msg}")

    # Step 2: Restore backtest folder from backup
    backtest_backup_path = REFINE_DIR / "backtest.backup"

    if backtest_backup_path.exists():
        try:
            # Remove current backtest folder
            if BACKTEST_RESULTS_DIR.exists():
                shutil.rmtree(BACKTEST_RESULTS_DIR)

            # Restore from backup (move, not copy)
            shutil.move(str(backtest_backup_path), str(BACKTEST_RESULTS_DIR))
            result["backtest_restored"] = True
            print(f"Restored: backtest.backup/ -> backtest/")
        except Exception as e:
            error_msg = f"Failed to restore backtest folder: {e}"
            result["errors"].append(error_msg)
            result["success"] = False
            print(f"ERROR: {error_msg}")
    else:
        error_msg = "backtest.backup/ not found - cannot restore"
        result["errors"].append(error_msg)
        result["success"] = False
        print(f"ERROR: {error_msg}")

    if result["success"]:
        print("REVERT completed: Backups restored, new files discarded")

    return result


def main():
    from echolon._internal.structured_logging import install_structured_logging
    install_structured_logging()
    parser = argparse.ArgumentParser(
        description="Post-decision handler for KEEP/REVERT workflow"
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--keep", action="store_true",
                       help="KEEP new files, delete backups")
    group.add_argument("--revert", action="store_true",
                       help="REVERT to backups, discard new files")

    args = parser.parse_args()

    if args.keep:
        result = execute_keep()
    else:
        result = execute_revert()

    print(json.dumps(result, indent=2, default=str))
    return 0 if result["success"] else 1


if __name__ == "__main__":
    sys.exit(main())
