"""Momentum breakout: enter LONG when close breaks N-bar high.

This example is paradigm-blind: ``regime`` on EntrySignalOutput is left unset
(see ``echolon/strategy/schemas.py``). Strategies that want regime-conditional
behavior register a classifier via ``echolon.indicators.registry`` and read it
through ``get_market_regime()`` — see qorka's TRS paradigm wiring for an example.
"""

from echolon.strategy.component import BaseComponent
from echolon.strategy.interfaces import OrderIntent
from echolon.strategy.schemas import EntrySignalOutput


class entry_rule(BaseComponent):
    def __init__(self, trading_engine, **params):
        super().__init__(trading_engine, **params)
        self.lookback = self.params["lookback"]

    def generate_signal(self) -> EntrySignalOutput:
        close = self.get_current_price()
        high_n = self.get_indicator(f"highest_high_{self.lookback}")
        if close > high_n:
            out = EntrySignalOutput(
                signal="LONG", strength=1.0, type="breakout_long",
                entry_reason=f"Close {close} > {self.lookback}-bar high {high_n}",
                intent=OrderIntent.ENTRY_LONG,
            )
        else:
            out = EntrySignalOutput(
                signal="HOLD", strength=0.0, type="hold",
                entry_reason="No breakout",
            )
        self.log_entry_output(out)
        return out
