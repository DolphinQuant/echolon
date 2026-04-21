## Refactor 2026-04-21 — backtest/live architecture

Callers (e.g. qorka) must update the following imports:

| Old path                                                   | New path                                                             |
|------------------------------------------------------------|----------------------------------------------------------------------|
| `echolon.backtest.engine_factory.EngineFactory`            | `echolon.engine.factory.EngineFactory`                               |
| `echolon.backtest.analyzers.*`                             | `echolon.backtest.metrics.analyzers.*`                               |
| `echolon.backtest.mfe_mae.*`                               | `echolon.backtest.metrics.mfe_mae.*`                                 |
| `echolon.backtest.portfolio_metrics.*`                     | `echolon.backtest.metrics.portfolio_metrics.*`                       |
| `echolon.backtest.reporting.*`                             | `echolon.backtest.metrics.reporting.*`                               |
| `echolon.backtest.utils.stats.*`                           | `echolon.backtest.metrics.stats.*`                                   |
| `echolon.live.state_writer.*`                              | `echolon._internal.atomic_state.*`                                   |
| `echolon.live.trading_slot.TradingSlot`                    | `echolon.live.slot.trading_slot.TradingSlot`                         |
| `echolon.live.capital_slot.CapitalSlot`                    | `echolon.live.slot.capital_slot.CapitalSlot`                         |
| `echolon.live.slot_aware_portfolio.*`                      | `echolon.live.slot.slot_aware_portfolio.*`                           |
| `echolon.live.portfolio_risk.PortfolioRiskOverlay`         | `echolon.live.slot.risk_overlay.PortfolioRiskOverlay`                |
| `echolon.live.data_logger.*`                               | `echolon.live.io.data_logger.*`                                      |
| `echolon.live.dashboard.*`                                 | `echolon.live.io.kpi_aggregator.*`                                   |
| `echolon.live.runner.TradingRunner`                        | `echolon.live.orchestrator.single.TradingRunner`                     |
| `echolon.live.portfolio_runner.PortfolioTradingRunner`     | `echolon.live.orchestrator.portfolio.PortfolioTradingRunner`         |

### Removed

- `echolon.live.platforms.ccxt` — dead stub files. CCXT support is not currently implemented; remove references.

### Deferred

- `AbstractLiveOrchestrator` extraction (planned Phase 8) was deferred because the duplication between `TradingRunner` and `PortfolioTradingRunner` is structural, not textual (different logger attributes, different log message wording, different helper signatures). Extracting shared code would require log-message-text changes or attribute renames — observable behaviour diffs beyond this PR's strict-refactor scope. Tracked as a follow-up.

### Preserved (no call-site changes needed)

- Class names: `EngineFactory`, `TradingRunner`, `PortfolioTradingRunner`, `PortfolioRiskOverlay`, `TradingSlot`, `CapitalSlot`, `SlotAwarePortfolio`
- Function names in `kpi_aggregator.py`: `generate_dashboard_data`, `aggregate_portfolio`, `load_equity_curve`, `save_portfolio_dashboard`
- Function names in `data_logger.py`: `save_trading_data_snapshot`, `save_trade_execution`, `load_trading_data_history`
- Function names in `atomic_state.py`: `write_state_atomically`, `update_heartbeat`
- All function / class signatures across the moved files
