"""RSI mean reversion: enter LONG on oversold."""

from echolon.strategy.component import BaseComponent
from echolon.strategy.interfaces import OrderIntent
from echolon.strategy.schemas import EntrySignalOutput


class entry_rule(BaseComponent):
    def __init__(self, trading_engine, **params):
        super().__init__(trading_engine, **params)
        self.rsi_period = self.params.get("rsi_period", 14)
        self.oversold = self.params.get("oversold", 30)

    def generate_signal(self) -> EntrySignalOutput:
        regime = self.get_market_regime()
        try:
            rsi = self.get_indicator(f"rsi_{self.rsi_period}")
        except Exception:
            rsi = None
        if rsi is not None and rsi < self.oversold:
            return EntrySignalOutput(
                signal="LONG", strength=1.0, type="mean_rev_long",
                entry_reason=f"RSI({self.rsi_period})={rsi} < {self.oversold}",
                intent=OrderIntent.ENTRY_LONG, regime=regime,
            )
        return EntrySignalOutput(
            signal="HOLD", strength=0.0, type="hold",
            entry_reason="Not oversold", regime=regime,
        )
