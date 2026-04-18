# Changelog

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
