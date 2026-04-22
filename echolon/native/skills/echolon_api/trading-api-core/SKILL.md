---
name: trading-api-core
description: Platform-agnostic trading strategy API patterns. Use when generating entry, exit, risk, or sizer components, or when working with indicators and BaseModel outputs.
type: skill
category: echolon_api
primary_scope: universal
echolon_version: unpinned
origin_module: task15_migration_from_qorka
---

# Trading API Core Patterns

## Three-Tier Indicator System (CRITICAL)

All indicator access MUST follow tier-specific naming:

### Tier 1: Indicators with Lookback
- **Format**: `f'{indicator_name}_{self.period}'`
- **Examples**: ADX, ATR, RSI, EMA, SMA, HIGHEST_HIGH, LOWEST_LOW
- **Code**: `f'adx_{self.adx_period}'` → `'adx_14'`
- **NEVER** use bare names for Tier 1 indicators

### Tier 2: Indicators with Special Parameters
- **Format**: Bare name only (uses ta_lib.py defaults)
- **Examples**: MACD, STOCH, BBANDS
- **Code**: `'macd_line'`, `'stoch_k'`, `'bbands_upper'`
- **NEVER** append parameters to Tier 2 indicators

### Tier 3: Indicators without Lookback
- **Format**: Bare name only
- **Examples**: AD, OBV, TRANGE, CDL patterns, market_regime
- **Code**: `'ad'`, `'obv'`, `'trange'`
- **IMPORTANT**: For market context, use frequency-specific methods:
  - INTERDAY: `get_market_regime()` → 'trending_up', 'ranging', etc.
  - INTRADAY: `get_session_phase()` → phase names vary by bar size (see INTRADAY.md)

## BaseModel Output Pattern (CRITICAL)

All components MUST return Pydantic BaseModel instances:

| Component | Return Type | Required Fields |
|-----------|-------------|-----------------|
| Entry | `EntrySignalOutput` | signal, strength, type, entry_reason, intent |
| Exit | `ExitSignalOutput` | should_exit, exit_reason, position_size, bars_since_entry, intent |
| Risk | `RiskOutput` | trading_allowed, risk_reason |
| Sizer | `SizerOutput` | calculated_size, signal_direction, sizing_reason, raw_size |

**Sizer MANDATORY Validation:**
```python
# MUST call before returning - validates non-negative integer
validated_size = self.validate_and_convert_position_size(raw_size)
```

**Access Pattern**: Use `.field` attribute access, NEVER `['field']` dict access.

**Single Output Pattern**:
```python
output = EntrySignalOutput(
    signal=signal,
    strength=strength,
    type=signal_type,
    entry_reason=reason,
    intent=intent,
    # Strategy-specific fields via extra='allow'
    rsi_value=rsi
)
self.log_entry_output(output)  # Log same instance
return output                   # Return same instance
```

## No Error Handling Policy (CRITICAL)

- **NEVER** use try-except blocks
- **NEVER** use `.get()` with default values
- **NEVER** add fallback logic
- **ALWAYS** use direct access: `self.params['key']`

All errors must propagate explicitly for debugging.

## Component Interface Contracts

```python
# Entry component
class entry_rule(BaseComponent):
    def generate_signal(self) -> EntrySignalOutput: ...

# Exit component
class exit_rule(BaseComponent):
    def should_exit(self) -> ExitSignalOutput: ...

# Risk component
class risk_manager(BaseComponent):
    def can_trade(self) -> RiskOutput: ...

# Sizer component
class position_sizer(BaseComponent):
    def calculate_size(self, signal_data: EntrySignalOutput) -> SizerOutput: ...
```

For complete interface specifications, see [INTERFACES.md](INTERFACES.md).
For BaseStrategy class documentation, see [STRATEGY.md](STRATEGY.md).
For architecture overview, see [ARCHITECTURE.md](ARCHITECTURE.md).

## Frequency-Specific Patterns

Strategies can be either **interday** (daily bars) or **intraday** (sub-daily bars).
The frequency is defined in `TradingContext` (loaded via `MarketFactory.from_session()` from `session/state.json`) and determines which hooks are applied.

| Frequency | Documentation | Key Features |
|-----------|--------------|--------------|
| Intraday | [INTRADAY.md](INTRADAY.md) | Session methods, VWAP, opening range, EOD close |
| Interday | [INTERDAY.md](INTERDAY.md) | Contract expiry, daily ATR, overnight gaps |

### Frequency-Agnostic Code Pattern (CRITICAL)

Session methods are only available in intraday mode. Use `hasattr()` guards:

```python
# CORRECT: Works for both frequencies
if hasattr(self, 'is_closing_phase') and self.is_closing_phase():
    # Intraday closing logic

# WRONG: Crashes in interday mode
if self.is_closing_phase():  # AttributeError!
```
