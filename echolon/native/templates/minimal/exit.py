"""Minimal exit rule."""

from echolon.quant_engine.core.base.base_component import BaseComponent
from echolon.quant_engine.types import ExitSignalOutput


class exit_rule(BaseComponent):
    def __init__(self, trading_engine, **params):
        super().__init__(trading_engine, **params)
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
        return ExitSignalOutput(
            should_exit=False, exit_reason="Template: holding",
            position_size=abs(pos.size), bars_since_entry=self.bars_held,
        )
