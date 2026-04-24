---
name: validation-backup
description: Backup and restore operations for strategy validation workflow. Sub-agent creates backup before changes. Validator/Exploitate agent executes post-decision (KEEP/REVERT).
type: skill
category: echolon_api
primary_scope: universal
echolon_version: unpinned
origin_module: task15_migration_from_qorka
---

# Validation Backup Skill

## Workflow Overview

```
Sub-Agent                          Validator/Exploitate Agent
    │                                        │
    ├─ 1. Create backup ──────────────────► │
    │    (before making changes)             │
    │                                        │
    ├─ 2. Make code changes                  │
    │                                        │
    ├─ 3. Run backtest                       │
    │                                        │
    ├─ 4. Return results ─────────────────► │
    │                                        │
    │                              5. Review metrics
    │                                        │
    │                              6. Decide KEEP/REVERT
    │                                        │
    │                              7. Execute post_decision.py
    │                                        │
```

## 1. Backup (Sub-Agent)

Before making any code changes, sub-agent creates backup. The scripts ship
inside the echolon package under `echolon/native/skills/echolon_api/validation-backup/scripts/`
(moved from the qorka-local `.claude/skills/` path during Task 15 migration).
Resolve the absolute path at call time so the command is install-location-agnostic:

```bash
python3 "$(python3 -c 'import echolon, os; print(os.path.join(os.path.dirname(echolon.__file__), "native/skills/echolon_api/validation-backup/scripts/backup.py"))')"
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

## 2. Post-Decision (Validator/Exploitate Agent)

After KEEP/REVERT decision, execute:

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

1. **Single backup**: Only one backup exists (`.backup` suffix)
2. **Sub-agent backs up**: Before any code changes
3. **Orchestrator decides**: KEEP or REVERT based on metrics
4. **Orchestrator executes**: post_decision.py after decision
5. **run_context validation**: KEEP blocked if backtest was debug mode
