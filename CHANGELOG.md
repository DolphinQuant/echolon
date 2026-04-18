# Changelog

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
