---
name: validation-backup
description: Back-up-then-restore primitive for risky strategy edits. Snapshot the strategy directory + backtest results before a change, run the change, then KEEP (delete the snapshot) or REVERT (restore the snapshot).
type: skill
category: echolon_api
primary_scope: universal
echolon_version: unpinned
---

# Validation Backup Skill

## Workflow Overview

```
1. Create backup     ──► snapshot strategy_code_dir/* + backtest_results_dir/
2. Make code changes ──► (your edit; coding agent, manual, or otherwise)
3. Run backtest      ──► `echolon backtest single <strategy_dir>`
4. Review metrics    ──► decide KEEP or REVERT
5. Post-decision     ──► KEEP (delete snapshots) | REVERT (restore from snapshots)
```

This is a generic "snapshot before risky edit" primitive — useful for any
iterative workflow that needs to A/B compare a code change against its
pre-change baseline. The scripts make no assumptions about *who* is making
the decision (a human, an LLM agent, a CI gate); they just provide the
mechanics.

## 1. Backup

Before making any code changes, run the backup script. It ships inside the
echolon package under
`echolon/native/skills/echolon_api/validation-backup/scripts/`. Resolve the
absolute path at call time so the command is install-location-agnostic.

**Default:** paths come from `PathsConfig.from_env()`, which resolves
`strategy_code_dir` and `backtest_results_dir` from the OSS-layout defaults
(`workspace/strategy/baseline/` and `workspace/backtest/`) or from
`ECHOLON_*` env-var overrides:

```bash
python3 "$(python3 -c 'import echolon, os; print(os.path.join(os.path.dirname(echolon.__file__), "native/skills/echolon_api/validation-backup/scripts/backup.py"))')"
```

**Override paths** (tests, non-default workspace layouts, host-app iteration loops with custom layouts):

```bash
python3 "$(python3 -c 'import echolon, os; print(os.path.join(os.path.dirname(echolon.__file__), "native/skills/echolon_api/validation-backup/scripts/backup.py"))')" \
    --strategy-dir /path/to/code --backtest-dir /path/to/backtest
```

**What Gets Backed Up** (with `.backup` suffix):
- `entry.py` → `entry.py.backup`
- `exit.py` → `exit.py.backup`
- `risk.py` → `risk.py.backup`
- `sizer.py` → `sizer.py.backup`
- `strategy.py` → `strategy.py.backup`
- `strategy_params.py` → `strategy_params.py.backup`
- `strategy_indicator_list.json` → `strategy_indicator_list.json.backup`
- `selected_robust_trial.json` → `selected_robust_trial.json.backup`
- `backtest/` → `backtest.backup/`

**Note**: Only ONE backup exists at a time. Running backup overwrites previous backup.

## 2. Post-Decision

After deciding KEEP or REVERT, execute the corresponding command. Both accept
the same optional `--strategy-dir` / `--backtest-dir` overrides as
`backup.py`; omit them to use `PathsConfig.from_env()`.

### KEEP Decision

```bash
python3 "$(python3 -c 'import echolon, os; print(os.path.join(os.path.dirname(echolon.__file__), "native/skills/echolon_api/validation-backup/scripts/post_decision.py"))')" --keep
```

This will:
1. Verify `backtest_results.json` has `run_context: "best_trial"`
2. If `run_context: "debug"` → **ERROR** (cannot keep debug results)
3. Delete all `.backup` files and `backtest.backup/` folder
4. Retain the new code and backtest results

### REVERT Decision

```bash
python3 "$(python3 -c 'import echolon, os; print(os.path.join(os.path.dirname(echolon.__file__), "native/skills/echolon_api/validation-backup/scripts/post_decision.py"))')" --revert
```

This will:
1. Restore all `.backup` files to original names
2. Restore `backtest.backup/` to `backtest/`
3. Discard the failed changes

## Files Backed Up

| File | Description |
|------|-------------|
| `entry.py` | Entry signal logic |
| `exit.py` | Exit signal logic |
| `risk.py` | Risk management |
| `sizer.py` | Position sizing |
| `strategy.py` | Strategy orchestration |
| `strategy_params.py` | Parameter definitions |
| `strategy_indicator_list.json` | Indicator configuration |
| `selected_robust_trial.json` | Selected trial parameters |

## Error Handling

All scripts return JSON with `success` field:
- `success: true` - Operation completed
- `success: false` - Operation failed, check `errors` array

Exit codes:
- `0` - Success
- `1` - Failure

## Key Principles

1. **Single backup**: only one backup exists at any time (`.backup` suffix). Re-running backup.py overwrites.
2. **Backup before any code change** — that's the entire safety contract.
3. **Decision is external**: the script doesn't decide KEEP vs REVERT; whoever drives the workflow does (a human, an LLM agent, a CI gate).
4. **`run_context` gate on KEEP**: post_decision.py refuses `--keep` if the latest backtest was run with `run_context: "debug"`. The intent is that you only KEEP results from a real Optuna best-trial run, not from a one-off debug invocation.
