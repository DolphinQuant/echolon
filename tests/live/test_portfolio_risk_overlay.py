"""Unit tests for PortfolioRiskOverlay — peak tracking and drawdown breach."""
from dataclasses import dataclass

import pytest

from echolon.live.slot.capital_slot import CapitalSlot
from echolon.live.slot.risk_overlay import PortfolioRiskOverlay


@dataclass
class _FakeSlot:
    """Minimal stand-in for TradingSlot — only what risk_overlay touches."""
    slot_id: str
    capital_slot: CapitalSlot


def _make_slot(slot_id: str, equity: float, initial: float = 100000.0) -> _FakeSlot:
    """Build a slot whose .capital_slot.equity matches `equity`.

    CapitalSlot.equity = initial_capital + realized_pnl + unrealized_pnl,
    so we set realized_pnl = (equity - initial). We do NOT call
    record_trade() because that would also update peak_equity, and
    risk_overlay only consumes capital_slot.equity (a property), not
    capital_slot.peak_equity.
    """
    cs = CapitalSlot(slot_id=slot_id, initial_capital=initial)
    cs.realized_pnl = equity - initial
    return _FakeSlot(slot_id=slot_id, capital_slot=cs)


def test_overlay_peak_equity_starts_at_zero(tmp_path):
    ov = PortfolioRiskOverlay(max_portfolio_drawdown_pct=15.0,
                              deploy_data_dir=str(tmp_path))
    assert ov.peak_equity == 0.0


def test_overlay_peak_equity_increases_monotonically(tmp_path):
    ov = PortfolioRiskOverlay(max_portfolio_drawdown_pct=15.0,
                              deploy_data_dir=str(tmp_path))
    slots = [_make_slot("al", 100000), _make_slot("cu", 100000), _make_slot("zn", 100000)]
    ov.check_portfolio_drawdown(slots)
    assert ov.peak_equity == 300000.0
    # Push higher
    slots = [_make_slot("al", 110000), _make_slot("cu", 100000), _make_slot("zn", 100000)]
    ov.check_portfolio_drawdown(slots)
    assert ov.peak_equity == 310000.0
    # Now drop — peak must NOT decrease
    slots = [_make_slot("al", 80000), _make_slot("cu", 100000), _make_slot("zn", 100000)]
    ov.check_portfolio_drawdown(slots)
    assert ov.peak_equity == 310000.0


def test_overlay_drawdown_breach_at_threshold(tmp_path):
    ov = PortfolioRiskOverlay(max_portfolio_drawdown_pct=15.0,
                              deploy_data_dir=str(tmp_path))
    slots = [_make_slot("al", 100000), _make_slot("cu", 100000), _make_slot("zn", 100000)]
    ov.check_portfolio_drawdown(slots)  # peak = 300k
    # Drop 16%: equity = 252k -> drawdown = 16% > 15% -> breach
    slots = [_make_slot("al", 84000), _make_slot("cu", 84000), _make_slot("zn", 84000)]
    ok = ov.check_portfolio_drawdown(slots)
    assert ok is False  # breached


def test_overlay_drawdown_ok_below_threshold(tmp_path):
    ov = PortfolioRiskOverlay(max_portfolio_drawdown_pct=15.0,
                              deploy_data_dir=str(tmp_path))
    slots = [_make_slot("al", 100000), _make_slot("cu", 100000), _make_slot("zn", 100000)]
    ov.check_portfolio_drawdown(slots)  # peak = 300k
    # Drop 10%: equity = 270k -> drawdown = 10% < 15% -> OK
    slots = [_make_slot("al", 90000), _make_slot("cu", 90000), _make_slot("zn", 90000)]
    ok = ov.check_portfolio_drawdown(slots)
    assert ok is True


def test_overlay_save_load_roundtrip(tmp_path):
    ov = PortfolioRiskOverlay(max_portfolio_drawdown_pct=15.0,
                              deploy_data_dir=str(tmp_path))
    slots = [_make_slot("al", 110000), _make_slot("cu", 100000), _make_slot("zn", 100000)]
    ov.check_portfolio_drawdown(slots)  # peak = 310k
    ov.save()
    # New overlay reads persisted state
    ov2 = PortfolioRiskOverlay(max_portfolio_drawdown_pct=15.0,
                               deploy_data_dir=str(tmp_path))
    ov2.load(active_slot_ids=["al", "cu", "zn"])
    assert ov2.peak_equity == 310000.0
