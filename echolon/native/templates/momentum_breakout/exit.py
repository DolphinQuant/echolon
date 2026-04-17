"""Momentum breakout: exit on N-day trailing low."""

from echolon.quant_engine.core.base.base_component import BaseComponent
from echolon.quant_engine.core.interfaces.trading_interfaces import OrderIntent
from echolon.quant_engine.types import ExitSignalOutput


class exit_rule(BaseComponent):
    def __init__(self, trading_engine, **params):
        super().__init__(trading_engine, **params)
        self.exit_lookback = self.params.get("exit_lookback", 10)
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
        close = self.get_current_price()
        try:
            low_n = self.get_indicator(f"low_{self.exit_lookback}")
        except Exception:
            low_n = None
        if low_n is not None and close < low_n:
            return ExitSignalOutput(
                should_exit=True,
                exit_reason=f"Close {close} < {self.exit_lookback}-day low {low_n}",
                position_size=abs(pos.size),
                bars_since_entry=self.bars_held,
                intent=OrderIntent.EXIT_LONG,
            )
        return ExitSignalOutput(
            should_exit=False, exit_reason="Holding",
            position_size=abs(pos.size), bars_since_entry=self.bars_held,
        )
