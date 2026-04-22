# Echolon Skills Index

Always-loaded index of skills shipped with the echolon package. Each
entry is one line. Skill bodies live at the paths shown; retrievers
load them on demand via the `query_skill(name)` tool.

## echolon_api — how to use echolon's public API

- [market_factory](echolon_api/market_factory/SKILL.md) — Factory entry point that builds a fully-wired TradingContext from session state (state.json + trading_target_*.json) or explicit market/instrument/frequency/bar_size parameters. — scope: universal
- [trading_context](echolon_api/trading_context/SKILL.md) — Immutable dataclass carrying market, instrument, frequency, bar_size, and TradingTarget — exposes properties (market_code, instrument_code, bars_per_day), bar_size-aware phase encode/decode callbacks, and frequency-scaled indicator defaults. — scope: universal
- [engine_factory](echolon_api/engine_factory/SKILL.md) — Factory for trading engines — composes a market adapter, frequency context, and market-mode-appropriate hooks (ContractAwareHook / SessionAwareHook) into a ready-to-use backtest or deploy engine from a TradingContext. — scope: universal
- [get_strategy_class](echolon_api/get_strategy_class/SKILL.md) — Returns a cached Backtrader-compatible strategy class (BacktraderStrategyBridge subclass) bound to a TradingContext; optional strategy_code_dir loads platform-agnostic strategy files from an arbitrary directory. — scope: universal
- [run_best_trial](echolon_api/run_best_trial/SKILL.md) — Runs a single Backtrader backtest using parameters from selected_robust_trial.json (TrialSelector output), optionally overriding the start/end dates for out-of-sample validation; returns the detailed results dict. — scope: universal
