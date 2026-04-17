# Changelog

## 0.3.0 — AI-Native Layer (unreleased)

### Added
- `echolon.native` subpackage with error system, validators, CLI, and templates
- `EchelonError` class hierarchy with 13 initial error codes
- `echolon` CLI with 5 commands: `validate`, `init-strategy`, `run`, `schema`, `examples`
- 3 strategy templates: `minimal`, `momentum_breakout`, `rsi_mean_reversion`
- 3 working examples at `examples/`
- `llms.txt` at repo root (AI agent entry point)
- `docs/` directory with QUICK_START, API_REFERENCE, COMPONENT_GUIDE, CONFIG_REFERENCE, PATTERNS, ERROR_CATALOG, and per-error docs

### Changed
- Added `typer>=0.9.0` as a dependency for the CLI

## 0.2.0 — Config Interface

### Breaking Changes
- BacktestRunner, OptunaOptimizer, WFARunner, and PortfolioBacktestRunner now require explicit configs
- Removed module-level globals from `echolon.config.quant_engine`

### Added
- BacktestConfig, OptunaConfig, IndicatorConfig Pydantic models
- `TradingContext.from_market()` classmethod
- `echolon.quick_start()` convenience helper

## 0.1.0 — Initial Release

Initial extraction from DolphinQuantStrategy monorepo.
