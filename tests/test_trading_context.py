"""Tests for TradingContext.from_market() constructor."""

from echolon.config.markets.core.context import TradingContext


def test_from_market_shfe_interday():
    ctx = TradingContext.from_market(
        market="shfe",
        instrument="cu",
        frequency="interday",
        bar_size="1d",
    )
    assert ctx.market_code == "SHFE"
    assert ctx.instrument_code == "cu"
    assert ctx.frequency == "interday"
    assert ctx.bar_size == "1d"
