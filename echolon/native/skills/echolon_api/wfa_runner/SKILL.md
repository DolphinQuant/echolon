---
name: wfa_runner
description: Orchestrates walk-forward analysis across expanding windows — per window runs Optuna optimization, TrialSelector, and OOS backtest; aggregates WFA metrics and Deployment Readiness Score; runs a final full-period backtest with the last window's parameters.
type: skill
category: echolon_api
primary_scope: universal
echolon_version: unpinned
origin_module: echolon_audit_phase0
---

# echolon.backtest.wfa.runner.WFARunner

## Purpose

`WFARunner` executes the standard walk-forward analysis pipeline used by the echolon optimization layer. For each window in `WFAConfig.windows` it: (1) filters pre-loaded indicators to the IS period, (2) runs an `OptunaOptimizer` study, (3) saves trials + best params, (4) runs `TrialSelector.select()` to pick a robust trial, (5) runs an OOS backtest via `run_best_trial(...)` for the window's OOS dates, (6) archives per-window OOS artefacts. After all windows complete it runs a `WalkForwardAnalyzer` to compute summary + per-window details, does one final full-period `run_best_trial` with the last window's parameters, and augments the resulting `backtest_results.json` with `wfa_summary`, `wfa_windows`, and a `drs` block (Deployment Readiness Score).

## Interface

```python
from echolon.config.markets.factory import MarketFactory
from echolon.config.optuna_config import OptunaConfig
from echolon.config.backtest_config import BacktestConfig
from echolon.backtest.wfa.runner import WFARunner
from echolon.backtest.wfa.window import WFAConfig, WFAWindow

ctx = MarketFactory.from_session()

config = WFAConfig(
    windows=[
        WFAWindow(window_id=1, is_start="2018-01-01", is_end="2021-12-31",
                  oos_start="2022-01-01", oos_end="2022-06-30"),
        WFAWindow(window_id=2, is_start="2018-01-01", is_end="2022-06-30",
                  oos_start="2022-07-01", oos_end="2022-12-31"),
        # ...
    ],
    trials_per_window=100,
    optimization_target="multi_objective",
    max_drawdown_threshold=15.0,
)

runner = WFARunner(
    ctx=ctx,
    config=config,
    optuna_config=OptunaConfig(n_trials=100),          # required
    backtest_config=BacktestConfig(...),               # required
    backtest_results_dir=Path("/path/to/output"),      # defaults to PathsConfig
)

# Runs everything, returns the final augmented backtest_results dict.
final = runner.run()
# final["wfa_summary"], final["wfa_windows"], final["drs"]
```

## When to use

- As the canonical orchestration entry for validating a strategy across expanding-windows — any time you want IS optimization + OOS replay + robustness metrics (WFE, OOS Sharpe distribution) rather than a single full-period Optuna run.
- When you need a Deployment Readiness Score (`drs`) written into `backtest_results.json`. `WFARunner` is the only echolon surface that currently computes DRS via `compute_drs(final_data, config=DRSConfig.from_trading_target(ctx.target.target))`.
- Do *not* run WFA from a shell loop calling `OptunaOptimizer.run()` + `TrialSelector.select()` yourself — `WFARunner` handles the cross-window memory hygiene (`del is_indicators, study; gc.collect()` between windows), the per-window archive under `backtest_results_dir/wfa_windows/window_<id>/`, the shared `market_adapter` + `strategy_class` objects, and the cache-clearing call (`clean_backtest_folder()`) at the start.
- Do *not* expect the final full-period backtest to stitch OOS windows. `WFARunner` runs a single `run_best_trial(ctx)` over the full `BacktestConfig` date range using the *last* window's `selected_robust_trial.json` — this gives consistent `performance_metrics`, trades, and equity curve from one parameter set rather than artificially stitched windows.

## Parameters / Returns

| Method | Args | Returns | Purpose |
|---|---|---|---|
| `__init__(ctx, config, optuna_config=<required>, backtest_config=<required>, backtest_results_dir=None)` | `TradingContext`, `WFAConfig`, configs, optional output dir (defaults to `PathsConfig.from_env().backtest_results_dir`) | — | Validates that both `optuna_config` and `backtest_config` are provided (raises `ValueError` otherwise). Sets `self.wfa_dir = output_dir / "wfa_windows"`. |
| `run()` | — | `Dict[str, Any]` | Full pipeline. Returns the augmented `backtest_results.json` content; returns `{}` if no windows completed. Deferred imports inside `run()` — the function explicitly imports `OptunaOptimizer`, `TrialSelector`, `run_best_trial`, `EngineFactory`, `get_strategy_class`, `load_backtest_data`, `load_indicator_metadata`, plus the strategy module's `optuna_search_space`/`DEFAULT_PARAMS`/`apply_shared_params`/`framework` symbols, after `clean_backtest_folder()`. |
| `_extract_is_sharpe(study)` | `optuna.Study` | `float` | `max(t.values[0] for t in completed_trials)` — works for both single- and multi-objective (values[0] is always sharpe in the convention here). |
| `_archive_window_artifacts(window, window_dir)` | `WFAWindow`, `Path` | `None` | Copies `backtest_results.json`, `backtest_trades.csv`, `equity_curve.csv` from `output_dir` to `window_dir/oos_*`. |
| `_build_final_results(last_window, wfa_summary, wfa_window_details)` | internals | `Dict[str, Any]` | Reads `backtest_results.json`, adds `wfa_summary` + `wfa_windows` + `drs`, copies last window's `optimization_trials.csv` up into `output_dir`, re-writes `backtest_results.json`. |

The per-window sequence inside `run()` (lines 115–247 of `runner.py`):
1. Slice IS → `is_indicators`.
2. `OptunaOptimizer(ctx, market_adapter, strategy_class, optuna_search_space, ...).run(...)`.
3. `optimizer.save_study_results(..., save_trials_csv=True)`.
4. `window.is_sharpe = _extract_is_sharpe(study)`.
5. `TrialSelector(..., default_params=DEFAULT_PARAMS, apply_shared_params_fn=apply_shared_params, param_classifications=framework.get_param_classifications()).select()` → writes `selected_robust_trial.json` into `PathsConfig.strategy_code_dir`.
6. `run_best_trial(ctx, start_date=window.oos_start, end_date=window.oos_end, backtest_config=self._backtest_config)` → writes `backtest_results.json`, `backtest_trades.csv`, `equity_curve.csv` to `output_dir`.
7. `_archive_window_artifacts(window, window_dir)`; `del is_indicators, study; gc.collect()`.

## Common errors

- **`ValueError: optuna_config is required ...` / `backtest_config is required ...`** — `__init__` invariants. Supply both or call `echolon.quick_start()` for defaults.
- **`WFA: No windows completed successfully`** (logger error, returns `{}`) — every window failed at step 1–6 (empty IS slice, no trials CSV, no robust trial, OOS raised). Inspect per-window `logger.warning` entries to identify which step bailed.
- **Per-window silent skips** — "Window N: No IS data, skipping" (empty `is_indicators`), "Window N: No trials CSV, skipping" (study failure), "Window N: No robust trial found, skipping OOS" (TrialSelector returned `None`). Each is a warning, not an error; the window's OOS results stay `None` and it is excluded from `completed_windows`.
- **Downstream `BT-001` / `BT-003`** — bubbled from the inner `OptunaOptimizer.run()` or `run_best_trial()`. See `docs/errors/BT-001.md`, `docs/errors/BT-003.md`.

## See also

- `optuna_optimizer` skill — wrapped per window.
- `trial_selector` skill — wrapped per window; writes the JSON that the OOS backtest reads.
- `run_best_trial` skill — called per window for OOS + once more for the final full-period backtest.
- `engine_factory` skill — `EngineFactory.create_market_adapter(ctx=self.ctx)` is shared across windows.
- `get_strategy_class` skill — same cached strategy class used in all windows.
- echolon docs: `echolon/backtest/wfa/{analyzer.py,drs_calculator.py,window.py}`.
