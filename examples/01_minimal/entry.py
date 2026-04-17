"""Minimal entry rule. TODO: replace hold-forever logic with your signal."""

from echolon.quant_engine.core.base.base_component import BaseComponent
from echolon.quant_engine.types import EntrySignalOutput


class entry_rule(BaseComponent):
    def __init__(self, trading_engine, **params):
        super().__init__(trading_engine, **params)

    def generate_signal(self) -> EntrySignalOutput:
        # TODO: replace this with your signal logic
        return EntrySignalOutput(
            signal="HOLD",
            strength=0.0,
            type="hold",
            entry_reason="Template: no entry logic yet",
            regime=self.get_market_regime(),
        )
