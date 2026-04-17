# Changelog

## 0.3.2 — AI-Native Layer (2026-04-17)

### Added
- `echolon.native` subpackage with error system, validators, CLI, and templates
- `EchelonError` class hierarchy with 13 initial error codes (VAL/CFG/STR/IND/PRM/DAT)
- `echolon` CLI with 5 commands: `validate`, `init-strategy`, `run`, `schema`, `examples`
- 3 strategy templates: `minimal`, `momentum_breakout`, `rsi_mean_reversion`
- 3 working examples at `examples/`
- `llms.txt` at repo root — AI agent entry point with Instructions section
- `docs/` directory with QUICK_START, API_REFERENCE, COMPONENT_GUIDE, CONFIG_REFERENCE, PATTERNS, ERROR_CATALOG, and per-error docs
- AI-native end-to-end smoke test (launch readiness gate)

### Changed
- Added `typer>=0.9.0` as a dependency for the CLI

### Notes
- 0.3.0 and 0.3.1 were yanked due to packaging issues (templates excluded, duplicate files)
- 0.3.2 is the first functional release of the AI-native layer

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
