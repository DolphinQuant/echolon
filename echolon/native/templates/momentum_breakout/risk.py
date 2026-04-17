"""Minimal risk manager."""

from echolon.quant_engine.core.base.base_component import BaseComponent
from echolon.quant_engine.types import RiskOutput


class risk_manager(BaseComponent):
    def __init__(self, trading_engine, **params):
        super().__init__(trading_engine, **params)

    def can_trade(self) -> RiskOutput:
        return RiskOutput(trading_allowed=True, risk_reason="Template: always allow")
