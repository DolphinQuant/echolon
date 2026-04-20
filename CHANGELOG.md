# Changelog

## Unreleased — Indicator API cleanup (pending release)

**Breaking changes.** The indicator subsystem's public surface has been
tightened to remove hardcoded monorepo paths, silent file I/O, and dead
flags. Callers now explicitly own configuration discovery.

Not published to PyPI yet — more adjustments expected before the next
release. This `Unreleased` section will be renamed to the final version
number when the release ships.

### Breaking

- `run_indicator_calculation` signature rewritten:
  - **Removed**: `selected_only`, `mode`, `optimize_regime`,
    `backtest_start_year`, `indicator_config`.
  - **Required now**: `output_dir`, `indicator_list`.
  - Retained: `ctx`, `trading_dates`, `use_parallel`, `regime_params`,
    `start_date`, `end_date` (all keyword-only after the required positionals).
- Schema change: `indicator_list` is now a flat dict
  `{indicator_name: {param: scalar_or_list}}`. List-valued params trigger
  Cartesian sweep across all value combinations. Legacy 3-bucket files
  (`indicators_with_lookback` / `indicators_without_lookback` /
  `indicators_with_special_params`) must be rewritten in the new format
  at their source.
- `echolon/indicators/config/` directory deleted. The library no longer
  ships curated indicator lists — callers supply their own. Monorepo users:
  files relocated to `DolphinQuantStrategy/modules/indicators/config/`.
- Echolon no longer reads/writes `<install_dir>/output/regime_params.json`.
  Regime params are required when `indicator_list` contains
  `market_regime`; callers obtain them via
  `echolon.indicators.optimize_regime_params()` or from their own
  persistence layer.
- `IndicatorProcessor._calculate_indicators_for_contract` and
  `_calculate_all_indicators_with_defaults` merged into a single
  flat-dict-driven compute path (`_compute_indicators_for_contract`).
  Deleted: `DEFAULT_INTERDAY_REGIME_PARAMS`, `_initialize_regime_params`,
  `_load_strategy_indicators` (hardcoded monorepo path).
- `TradingContext` pruned of 17 dead methods:
  `currency`, `is_24h`, `tick_size`, `sessions`,
  `design_paradigm_description`, `bars_per_hour`,
  `trading_minutes_per_day`, `get_session_bars`, `get_phase_for_time`,
  `get_phase_for_time_bar_aware`, `is_trading_time`, `get_phase_bars`,
  `get_phase_buffer_bars`, `calculate_commission`, `calculate_margin`,
  `calculate_contract_value`, `to_dict`.

### Added

- `echolon.indicators.optimize_regime_params(ctx, n_trials, ...)` —
  public helper for callers who need optimized regime-classification
  hyperparameters. Replaces the silent first-call Optuna run.
- `echolon.indicators.schema` — Pydantic v2 schema + expansion helpers
  for the flat-dict `indicator_list` format, including Cartesian param
  sweep (`expand_params_spec`, `expand_param`, `IndicatorList`).
- `echolon indicators list` CLI subcommand — dumps the library's
  indicator capabilities (name, cluster, supported frequencies). Useful
  as a starting template when constructing your own `indicator_list`.

### Removed

- `echolon/config/feature_flags.py` (Qorka concern, never library
  infrastructure).
- `echolon/indicators/utils/indicator_loader.py` (library ships no
  indicator configs to load — callers own their JSONs).
- `echolon/indicators/config/` (6 files moved to consumer repo).

### Migration guide (for when release ships)

Before:
```python
run_indicator_calculation(
    ctx, selected_only=True, use_parallel=True,
    start_date="2020-01-01", end_date="2024-12-31",
)
```

After:
```python
import json
with open("strategy_indicator_list.json") as f:
    indicator_list = json.load(f)
    # File must already be in flat-dict form.

from echolon.indicators import optimize_regime_params
regime_params = optimize_regime_params(ctx) if "market_regime" in indicator_list else None

run_indicator_calculation(
    ctx=ctx,
    output_dir="./data/indicators",
    indicator_list=indicator_list,
    regime_params=regime_params,
    start_date="2020-01-01", end_date="2024-12-31",
)
```

---

## 0.1.1 — Deployment CLI + public dashboard API (2026-04-18)

v0.4.0 was deleted from PyPI; this release restarts the version series at the
lowest clean version (0.1.0 – 0.4.0 wheel filenames are burned by PyPI's
filename-reuse policy, so 0.1.1 is the floor).

### Added

- `echolon deploy single|portfolio|portfolio-cycle` CLI subcommands — a user
  with only echolon installed can now run live trading: supply a strategy
  directory + `portfolio_deploy_config.json`, run
  `echolon deploy portfolio --config my.json`. No private deps.
- `echolon backtest portfolio` CLI subcommand — pre-deployment validation
  runs continuous + per-window fresh-capital backtests from the same config
  used for live deployment.
- Public dashboard aggregator API under `echolon.live`:
  `aggregate_portfolio`, `load_slot_state`, `load_equity_curve`. Downstream
  dashboard consumers no longer need to reach into `echolon.live.dashboard`
  privates.
- Schema-versioned disk contract: `strategy_state.json` and `heartbeat.json`
  now include a `schema_version: "1.0"` field. Atomic tmp-file-then-rename
  writes prevent readers from seeing partial files.
- `workspace/deploy/heartbeat.json` written after each trading cycle —
  consumers can alert on staleness (>2× cycle interval) to detect a hung
  trading process.
- `DeployConfig` gained `market`, `instrument`, `frequency`, `bar_size`,
  `initial_capital` fields so `deploy_config.json` is self-contained (no
  separate session state file needed).
- `PortfolioDeployConfig.load()` now resolves `strategy_code_dir` and
  `trial_params_path` relative to the config file's directory — strategies
  can live anywhere on disk, referenced relatively from the config.

### Removed

- `echolon.live.dashboard.send_dashboard_data`,
  `send_portfolio_dashboard_data`, `_post_json`, hardcoded backend URL.
  HTTP POST to a specific backend is a consumer concern, not a library
  concern.

### Migration

Prior releases are unaffected — this release is additive on top of v0.4.0.
If you were importing the removed sender helpers, write your own HTTP
client; see the `goingmerry` repo for a reference implementation using
`urllib`.

---

## 0.4.0 — Clean architecture restart (2026-04-18)

First public-ready release of Echolon. The prototype series (0.1.0–0.3.2) was removed from PyPI; this release starts the clean versioning line. Version bumped to 0.4.0 rather than 0.1.0 because PyPI does not allow reusing filenames from deleted versions.

### Architecture

- Module reorganization: the old catch-all `quant_engine/` has been decomposed into sibling top-level modules: `backtest/`, `live/`, `strategy/`, `markets/`.
- `data_pipeline/` renamed to `data/` (shorter, pandas-style).
- `errors.py` promoted to the top-level namespace (errors are cross-cutting).
- Schemas colocated with their owning domain; common ones re-exported from `echolon/__init__.py`.
- Production strategies (`cu_s1`, `al_s1`, `zn_s1`) removed from the library — proprietary IP belongs in private repos, not open source.
- `lib/` distributed to domains: `regime_utils` → `indicators/utils/`, `stats_utils` → `backtest/utils/`, `strategy_log` → `strategy/utils/`, `json_utils` → `_internal/`.
- `config/quant_engine.py` merged into `config/settings.py`.

### Added

- `echolon migrate <codebase>` CLI subcommand for automatic import rewrites from the prototype layout. Pass `--dry-run` to preview.
- Top-level convenience imports: `EchelonError`, `BacktestConfig`, `OptunaConfig`, `IndicatorConfig`, `TradingContext`, `quick_start`, `run_backtest`, `run_data_pipeline`, and signal schemas (`EntrySignalOutput`, `ExitSignalOutput`, `RiskOutput`, `SizerOutput`, `OrderIntent`).

### Migration for prototype users

Run `echolon migrate <your_codebase>` to rewrite old import paths. Use `--dry-run` first to preview.
