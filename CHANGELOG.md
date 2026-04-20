# Changelog

## Unreleased — Indicator API + Data module cleanup (pending release)

**Breaking changes.** The indicator subsystem and data module public
surfaces have both been tightened — removing hardcoded monorepo paths,
silent file I/O, dead flags, and vendor-SDK coupling. Callers now
explicitly own configuration discovery for both indicators and data.

Not published to PyPI yet — more adjustments expected before the next
release. This `Unreleased` section will be renamed to the final version
number when the release ships.

### Data module cleanup (breaking)

- `SHFEApiDayExtractor.generate_trading_calendar` now requires
  `source_path: str`. SHFE has no public trading-calendar API, so
  callers must derive one from the official holiday schedule
  (shfe.com.cn) and pass its path. Previously silently read from a
  dead hardcoded path (`echolon/../../../quant_engine/deploy/config/
  trading_calendar.csv`) that FileNotFound-errored on every live-deploy
  call post-reorg. A `ValueError` with install guidance now fires when
  `source_path` is missing.
- `DeployConfig` gains `trading_calendar_path: str = ""` field;
  `PortfolioDeployConfig.DeploySettings` gains the same. Both resolve
  relative to the config file's directory.
- `echolon/live/runner.py` + `echolon/live/portfolio_runner.py` now
  pass `source_path=self.config(.deploy)?.trading_calendar_path` when
  calling `generate_trading_calendar`.
- Extractors no longer default `output_dir` to `PROJECT_ROOT / "data"
  / ...`. Callers must pass `output_dir` explicitly (same pattern as
  indicator `output_dir` in the indicator cleanup). Affects all four
  extractors: SHFEFileDayExtractor, SHFEApiDayExtractor, SHFEApiMinuteExtractor,
  BinancePerpetualExtractor.
- `echolon` no longer imports `xtquant`. `SHFEApiMinuteExtractor`
  requires an injected client conforming to the new `XtdataClient`
  protocol defined in `echolon.data.extractors.base`.
- `run_data_pipeline` signature stripped: removed `source`, `client`,
  `present_date` params. It is file-based only. New
  `echolon.data.run_live_data_update(ctx, client, ...)` handles live
  incremental extraction. The `source="qmt"` string leak of
  broker-specific vocabulary is gone.
- `BaseExtractor.capabilities: ClassVar[Set[str]]` — every extractor
  declares its capabilities explicitly (batch, incremental,
  calendar_generate, calendar_load, main_contract). Callers check
  `"incremental" in extractor.capabilities` instead of
  `hasattr(extractor, "update_incremental")` duck-typing.
- Loader functions gain optional `path=None` kwarg:
  `load_ohlcv`, `load_contract_ohlcv`, `load_trading_calendar`,
  `get_trading_dates`, `is_trading_day`, `SessionAvailabilityLoader`,
  `get_session_availability_loader`. When `path` is set, loaders
  bypass the `MARKET_DATA_DIR / {market} / {asset} / ...` convention.

### Config surface alignment (IndicatorConfig wired in)

- `IndicatorConfig` is now the single source of truth for indicator
  period caps. Previously the `IndicatorConfig` class existed but had
  no production callers; `INDICATOR_PERIOD_CAPS` /
  `INTRADAY_INDICATOR_PERIOD_CAPS` module-level dicts in
  `echolon/config/settings.py` (and a duplicate pair in
  `qorka/config/quant_engine.py`) were the authoritative values.
- Call sites rewired to accept an injected `IndicatorConfig`:
  `InterdayRegimeOptimizer.__init__` and the `optimize_regime_params`
  wrapper gain an `indicator_config: Optional[IndicatorConfig] = None`
  param; `StrategyParamsGenerator.__init__` gains the same.
  When omitted, `IndicatorConfig()` defaults apply (identical values
  to the old module constants).
- Deleted: `INDICATOR_PERIOD_CAPS` / `INTRADAY_INDICATOR_PERIOD_CAPS`
  from `echolon/config/settings.py` and from
  `qorka/config/quant_engine.py`. Added `build_indicator_config()`
  factory in `qorka/config/quant_engine.py` for symmetry with the
  existing `build_backtest_config` / `build_optuna_config` /
  `build_wfa_config` factories.

### Data module cleanup (polish / renames)

- Unused skip-flags dropped from data-pipeline entry points:
  `run_data_pipeline` loses `skip_standardization`, `skip_splitting`,
  `skip_calendar` (no callers in echolon or qorka);
  `run_live_data_update` loses `skip_standardization`, `skip_splitting`
  (also no callers). `skip_extraction` stays on `run_data_pipeline`
  (used by `qorka/orchestrator/strategy_dev.py`) and `skip_calendar`
  stays on `run_live_data_update` (used by
  `echolon/live/{runner,portfolio_runner}.py` where the calendar is
  pre-ensured separately).
- `skip_extraction=True` is now honest: `_load_source_data` only reads
  pre-extracted `sort_by_date.csv` and returns `None` (with a helpful
  warning) if absent. The old Excel fallbacks silently re-ran
  `extract_raw(save=False)` — defeating the purpose of the flag.
  Callers who want the fallback must run once with
  `skip_extraction=False` to populate the CSV first.
- Data-pipeline entry-point modules renamed to make the pair parallel
  and self-describing: `echolon/data/run.py` → `backtest_data.py`
  and `echolon/data/live.py` → `live_data.py`. Public function names
  (`run_data_pipeline`, `run_live_data_update`) are unchanged, and the
  preferred import path remains `from echolon.data import ...` — the
  module-rename only affects callers that deep-imported from
  `echolon.data.run` / `echolon.data.live`.
- SHFE extractors renamed to mark source explicitly (file vs api):
  `SHFEDayExtractor` → `SHFEFileDayExtractor`
  (`day_extractor.py` → `file_day_extractor.py`),
  `SHFELiveDayExtractor` → `SHFEApiDayExtractor`
  (`live_day_extractor.py` → `api_day_extractor.py`),
  `SHFEMinuteExtractor` → `SHFEApiMinuteExtractor`
  (`minute_extractor.py` → `api_minute_extractor.py`). The old
  "Day/Minute" names silently meant "file + Day" or "api + Minute",
  and "Live" mixed source and mode axes. No compat shim.
- `echolon/data/loaders/shfe_loader.py` renamed to
  `backtest_data_loader.py`. No compat shim (pre-1.0 hard rename);
  update your imports accordingly.
- `echolon/data/loaders/session_availability_loader.py` split:
  `SessionDayInfo` dataclass and `build_expected_bars()` factory
  relocated to the new `echolon/data/transformers/
  session_availability_builder.py`. Loader file shrunk 476 → 330 LOC.
- `echolon/data/loaders/contract_data.py` + `contract_utils.py`
  merged into a single `contract_loader.py` (orthogonal concerns,
  no duplicate logic; 446 total LOC).
- `echolon/data/schemas.py` pruned from 569 → 139 LOC. Deleted:
  `SchemaConfig`, `StandardSchema`, `SCHEMA_CONFIGS`, `get_schema`,
  `validate_dataframe`, standalone `get_missing_columns` — all had
  zero external callers. Kept: `MarketType`, `FrequencyType`,
  `OHLCVSchema`, `OHLCV_COLUMNS` + related constants (live callers
  across echolon + monorepo).
- `echolon.data.__init__` expanded from 3 → 33 re-exports. The
  public surface now includes entry points (`run_data_pipeline`,
  `run_live_data_update`), extractors, loaders, and transformers —
  all importable directly from `echolon.data`.

### Indicator API cleanup (breaking)

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
