from __future__ import annotations

import datetime as dt

import pytest

from echolon.live.book import (
    BookRiskOverlay,
    BookRunner,
    DiffOrder,
    TargetExecutor,
    load_live_panel_view,
)
from echolon.portfolio import BookState, TargetBook


class FakeRouter:
    def __init__(self) -> None:
        self.orders: list[dict] = []
        self.tripped_reasons: list[str] = []

    def submit_order(self, *, intent, symbol, volume, slot_id, intended_price=None):
        self.orders.append(
            {
                "intent": intent,
                "symbol": symbol,
                "volume": volume,
                "slot_id": slot_id,
                "intended_price": intended_price,
            }
        )

    def trip_circuit(self, reason: str) -> None:
        self.tripped_reasons.append(reason)


def test_target_executor_submits_only_required_position_diffs():
    router = FakeRouter()
    executor = TargetExecutor(
        router=router,
        book_id="book-1.0.0-g1",
        symbol_map={"al": "al2608.SF", "cu": "cu2608.SF", "rb": "rb2608.SF", "zn": "zn2608.SF"},
    )
    target = TargetBook(
        date=dt.date(2026, 7, 8),
        targets={"al": 0, "cu": 0, "rb": 2, "zn": -3},
    )

    submitted = executor.execute(target, current_lots={"al": 1, "cu": -1})

    assert submitted == [
        DiffOrder(instrument="al", symbol="al2608.SF", intent="EXIT_LONG", volume=1),
        DiffOrder(instrument="cu", symbol="cu2608.SF", intent="EXIT_SHORT", volume=1),
        DiffOrder(instrument="rb", symbol="rb2608.SF", intent="ENTRY_LONG", volume=2),
        DiffOrder(instrument="zn", symbol="zn2608.SF", intent="ENTRY_SHORT", volume=3),
    ]
    assert [order["intent"] for order in router.orders] == [
        "EXIT_LONG",
        "EXIT_SHORT",
        "ENTRY_LONG",
        "ENTRY_SHORT",
    ]


def test_target_executor_fails_loudly_when_symbol_mapping_is_missing():
    executor = TargetExecutor(router=FakeRouter(), book_id="book-1", symbol_map={})
    target = TargetBook(date=dt.date(2026, 7, 8), targets={"al": 1})

    with pytest.raises(KeyError, match="missing live symbol"):
        executor.execute(target, current_lots={})


def test_book_risk_overlay_trips_router_on_drawdown_breach():
    router = FakeRouter()
    overlay = BookRiskOverlay(
        max_drawdown_pct_of_equity=10.0,
        router=router,
        peak_equity_rmb=100_000.0,
    )
    book = BookState(
        date=dt.date(2026, 7, 8),
        equity_rmb=89_999.0,
        cash_rmb=89_999.0,
        margin_used_rmb=0.0,
        positions={},
    )

    result = overlay.check(book)

    assert result.halt is True
    assert result.reason == "book_drawdown"
    assert router.tripped_reasons == ["book_drawdown: 10.00% > 10.00%"]


def test_book_runner_refuses_to_execute_when_risk_overlay_halts():
    router = FakeRouter()
    overlay = BookRiskOverlay(
        max_drawdown_pct_of_equity=1.0,
        router=router,
        peak_equity_rmb=100_000.0,
    )
    runner = BookRunner(
        book_id="book-1",
        strategy=lambda _view, _book: TargetBook(date=dt.date(2026, 7, 8), targets={"al": 1}),
        executor=TargetExecutor(router=router, book_id="book-1", symbol_map={"al": "al2608.SF"}),
        risk_overlay=overlay,
    )
    book = BookState(
        date=dt.date(2026, 7, 8),
        equity_rmb=98_900.0,
        cash_rmb=98_900.0,
        margin_used_rmb=0.0,
        positions={},
    )

    result = runner.run_once(view=object(), book=book, current_lots={})

    assert result.halted is True
    assert result.orders == []
    assert router.orders == []


def test_load_live_panel_view_uses_panel_data_class(monkeypatch, tmp_path):
    calls = []

    class FakePanel:
        def view(self, date):
            calls.append(date)
            return {"date": date}

    class FakePanelData:
        @classmethod
        def load(cls, snapshot_dir):
            calls.append(snapshot_dir)
            return FakePanel()

    monkeypatch.setattr("echolon.live.book.PanelData", FakePanelData)

    view = load_live_panel_view(tmp_path / "live_snapshot", dt.date(2026, 7, 8))

    assert view == {"date": dt.date(2026, 7, 8)}
    assert calls == [tmp_path / "live_snapshot", dt.date(2026, 7, 8)]
