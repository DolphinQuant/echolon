# Component Guide

Every Echolon strategy has 4 components. This guide explains each one.

## entry_rule (entry.py)

**Class name:** `entry_rule` (exact — required by StrategyLoader)
**Base:** `BaseComponent`
**Method:** `generate_signal() -> EntrySignalOutput`

Called every bar when there is no open position and no pending orders.

**Example:**

```python
from echolon.quant_engine.core.base.base_component import BaseComponent
from echolon.quant_engine.core.interfaces.trading_interfaces import OrderIntent
from echolon.quant_engine.types import EntrySignalOutput


class entry_rule(BaseComponent):
    def __init__(self, trading_engine, **params):
        super().__init__(trading_engine, **params)
        self.rsi_period = self.params["rsi_period"]

    def generate_signal(self) -> EntrySignalOutput:
        rsi = self.get_indicator(f"rsi_{self.rsi_period}")
        regime = self.get_market_regime()
        if rsi < 30:
            return EntrySignalOutput(
                signal="LONG", strength=1.0,
                type="oversold_entry",
                entry_reason=f"RSI({self.rsi_period})={rsi} < 30",
                intent=OrderIntent.ENTRY_LONG,
                regime=regime,
            )
        return EntrySignalOutput(
            signal="HOLD", strength=0.0, type="hold",
            entry_reason="Not oversold", regime=regime,
        )
```

**Common errors:**
- VAL-001: missing required field
- VAL-003: wrong __init__ signature
- IND-001: uppercase indicator name

## exit_rule (exit.py)

**Class name:** `exit_rule`
**Base:** `BaseComponent`
**Method:** `should_exit() -> ExitSignalOutput`

Called every bar when there is an open position.

Stateful exit rules (trailing stops, bars-held counters) must reset their state when there is no position. See the minimal template's `exit.py`.

## risk_manager (risk.py)

**Class name:** `risk_manager`
**Base:** `BaseComponent`
**Method:** `can_trade() -> RiskOutput`

Called at the start of every bar. Returns `trading_allowed=True` to permit trading, `False` to block all new entries.

Use cases: max daily loss, max consecutive losses, trading-hours filter.

## position_sizer (sizer.py)

**Class name:** `position_sizer`
**Base:** `BaseComponent`
**Method:** `calculate_size(signal_data: EntrySignalOutput) -> SizerOutput`

Called after `entry_rule.generate_signal()` produces a non-HOLD signal. Receives the signal (so sizer can branch on regime, strength, etc.).

The sizer MUST call `self.validate_and_convert_position_size(raw_float)` before setting `calculated_size` — this rounds to whole contracts and handles edge cases.

## Data access helpers

All components inherit these helpers from `BaseComponent`:

- `self.get_current_price() -> float` — close of current bar
- `self.get_indicator(name: str) -> float` — value of pre-computed indicator (use lowercase names!)
- `self.get_market_regime() -> str` — one of: `ranging`, `trending_up`, `trending_down`, `volatile`
- `self.params: dict` — parameters from strategy_params.py
- `self.portfolio: IPortfolio` — access position info
- `self.validate_and_convert_position_size(float) -> int` — sizer helper

## Strategy coordinator (strategy.py)

**Class name:** `strategy_main`
**Base:** `BaseStrategy`
**Method:** `_execute_bar() -> None` (not `on_bar`)

The canonical pattern:

```python
def _execute_bar(self) -> None:
    risk_out = self.risk_manager.can_trade()
    if not risk_out.trading_allowed:
        return
    if self.has_position() and not self.has_pending_orders():
        exit_out = self.exit_rule.should_exit()
        if exit_out.should_exit and exit_out.intent is not None:
            self.exit(exit_out.intent)
            return
    if not self.has_position() and not self.has_pending_orders():
        entry_out = self.entry_rule.generate_signal()
        if entry_out.signal != "HOLD" and entry_out.intent is not None:
            sizer_out = self.position_sizer.calculate_size(entry_out)
            if sizer_out.calculated_size > 0:
                self.entry(entry_out.intent, sizer_out.calculated_size)
```

Every bundled template uses this exact pattern. Only customize if your strategy truly needs a different structure.
