---
name: market_factory
description: Factory entry point that builds a fully-wired TradingContext from session state (state.json + trading_target_*.json) or explicit market/instrument/frequency/bar_size parameters.
type: skill
category: echolon_api
primary_scope: universal
echolon_version: unpinned
origin_module: echolon_audit_phase0
---

# echolon.config.markets.factory.MarketFactory

## Purpose

`MarketFactory` is the single entry point for obtaining a configured `TradingContext`. It reads the session's `state.json` (and the matching `trading_target_{intraday,interday}.json`), resolves the target market config (SHFE, CRYPTO, ...), looks up the instrument spec, attaches market-specific phase encode/decode functions, and returns a ready-to-use `TradingContext`. Every downstream module — backtest, strategy, evaluation — should obtain its context via this factory rather than constructing `TradingContext` directly or reading session files ad hoc.

## Interface

```python
from echolon.config.markets.factory import MarketFactory

# 1. Most common: build from session state (uses PathsConfig.from_env()
#    for session_dir and output_dir unless overridden).
ctx = MarketFactory.from_session()

# 2. Explicit construction (tests, ad-hoc scripts, CLI tools).
ctx = MarketFactory.create(
    market="SHFE",
    instrument="al",
    frequency="intraday",
    bar_size="5m",
)

# 3. Load just the TradingTarget (when you need user_request / raw target
#    but not a full TradingContext).
target = MarketFactory.load_target()

# 4. Flexible instrument lookup (by code OR human name).
spec = MarketFactory.get_instrument_flexible("SHFE", "aluminum")  # or "al"

# 5. Introspection helpers.
cfg       = MarketFactory.get_market_config("SHFE")
all_codes = MarketFactory.list_instruments("SHFE")
```

## When to use

- At every module entry point that needs market/instrument/frequency info — call `MarketFactory.from_session()` and pass the returned `TradingContext` down via dependency injection.
- In CLI commands and orchestrators (e.g. qorka's `strategy_dev.StrategyDev`) that already have `session/state.json` written and need a single consistent context for the whole run.
- In tests or one-off scripts where you want to bypass session state — use `MarketFactory.create(...)` with explicit parameters.
- When you need to validate that a market/instrument combination is supported before doing heavier work — `get_instrument_flexible` returns `None` rather than raising.
- Do *not* instantiate `TradingContext` by hand. The factory is responsible for wiring the phase encode/decode callbacks correctly for each market and bar size.

## Parameters / Returns

| Method | Args | Returns | Purpose |
|---|---|---|---|
| `from_session(session_path=None, *, session_dir=None, output_dir=None)` | Optional overrides; defaults resolved via `PathsConfig.from_env()` | `TradingContext` | Primary entry point. Prefers `output_dir/target.json` if present; else loads `session/state.json` + `trading_target_*.json`. |
| `create(market, instrument, frequency, bar_size, target=None)` | market code (`"SHFE"`/`"CRYPTO"`), instrument code, `"intraday"` or `"interday"`, bar size string, optional `TradingTarget` | `TradingContext` | Explicit construction. Raises `ValueError` for unsupported market or instrument. |
| `load_target(session_path=None, *, session_dir=None, output_dir=None)` | Same as `from_session` | `TradingTarget` | Returns just the validated `TradingTarget` (includes `user_request`), without constructing a context. |
| `get_market_config(market)` | market code | `MarketConfig \| None` | Raw market config with timezone, sessions, instrument registry. |
| `get_instrument(market, instrument)` | market code, instrument code | `InstrumentSpec \| None` | Strict lookup by code. |
| `get_instrument_flexible(market, identifier)` | market code, code OR human name | `InstrumentSpec \| None` | Lookup by either `"al"` or `"aluminum"`. Case-insensitive. |
| `list_instruments(market)` | market code | `list[str]` | All supported instrument codes for the market. |
| `clear_cache()` | — | `None` | Clears the internal `_market_configs` cache. For tests only. |

## Common errors

- **`ValueError: Unsupported market: '...'`** — `create` / `get_instrument_flexible` was called with a market code outside `{'SHFE', 'CRYPTO'}`. Add a loader branch in `MarketFactory._load_market` to register the new market.
- **`ValueError: Unsupported instrument: '...' for market '...'`** — the instrument code/name is not in that market's `instruments` registry. Check `MarketFactory.list_instruments(market)` or the market's `config.py`.
- **`FileNotFoundError`** on `from_session` — `session/state.json` is missing. Most commonly the caller forgot to set `ECHOLON_SESSION_DIR` (see `PathsConfig.from_env()`) or the session wasn't initialised. Related: `CFG-002` in `docs/ERROR_CATALOG.md`.
- **`pydantic.ValidationError`** from `TradingTarget.load` / `TradingTargetConfigSchema.model_validate` — the session or trading-target JSON is structurally invalid. Inspect the raised error; no Echolon error code is issued yet for this path.

## See also

- `trading_context` skill — the `TradingContext` object `MarketFactory` returns
- echolon docs: `docs/CONFIG_REFERENCE.md`, `docs/COMPONENT_GUIDE.md`
