# Echolon Skills Index

Always-loaded index of skills shipped with the echolon package. Each
entry is one line. Skill bodies live at the paths shown; retrievers
load them on demand via the `query_skill(name)` tool.

## echolon_api — how to use echolon's public API

- [market_factory](echolon_api/market_factory/SKILL.md) — Factory entry point that builds a fully-wired TradingContext from session state (state.json + trading_target_*.json) or explicit market/instrument/frequency/bar_size parameters. — scope: universal
