"""Momentum breakout: enter LONG when close breaks N-day high."""

from echolon.quant_engine.core.base.base_component import BaseComponent
from echolon.quant_engine.core.interfaces.trading_interfaces import OrderIntent
from echolon.quant_engine.types import EntrySignalOutput


class entry_rule(BaseComponent):
    def __init__(self, trading_engine, **params):
        super().__init__(trading_engine, **params)
        self.lookback = self.params.get("lookback", 20)

    def generate_signal(self) -> EntrySignalOutput:
        regime = self.get_market_regime()
        close = self.get_current_price()
        try:
            high_n = self.get_indicator(f"high_{self.lookback}")
        except Exception:
            high_n = None
        if high_n is not None and close > high_n:
            return EntrySignalOutput(
                signal="LONG", strength=1.0, type="breakout_long",
                entry_reason=f"Close {close} > {self.lookback}-day high {high_n}",
                intent=OrderIntent.ENTRY_LONG, regime=regime,
            )
        return EntrySignalOutput(
            signal="HOLD", strength=0.0, type="hold",
            entry_reason="No breakout", regime=regime,
        )
