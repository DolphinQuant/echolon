"""RSI mean reversion: exit on overbought."""

from echolon.quant_engine.core.base.base_component import BaseComponent
from echolon.quant_engine.core.interfaces.trading_interfaces import OrderIntent
from echolon.quant_engine.types import ExitSignalOutput


class exit_rule(BaseComponent):
    def __init__(self, trading_engine, **params):
        super().__init__(trading_engine, **params)
        self.rsi_period = self.params.get("rsi_period", 14)
        self.overbought = self.params.get("overbought", 70)
        self.bars_held = 0

    def should_exit(self) -> ExitSignalOutput:
        pos = self.portfolio.get_position()
        if not pos or pos.size == 0:
            self.bars_held = 0
            return ExitSignalOutput(
                should_exit=False, exit_reason="No position",
                position_size=0.0, bars_since_entry=0,
            )
        self.bars_held += 1
        try:
            rsi = self.get_indicator(f"rsi_{self.rsi_period}")
        except Exception:
            rsi = None
        if rsi is not None and rsi > self.overbought:
            return ExitSignalOutput(
                should_exit=True,
                exit_reason=f"RSI={rsi} > {self.overbought}",
                position_size=abs(pos.size),
                bars_since_entry=self.bars_held,
                intent=OrderIntent.EXIT_LONG,
            )
        return ExitSignalOutput(
            should_exit=False, exit_reason="Holding",
            position_size=abs(pos.size), bars_since_entry=self.bars_held,
        )
