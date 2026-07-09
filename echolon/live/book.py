"""Generic live book execution primitives for the bundle-era path.

This module is deliberately broker-light: it converts target lots into
OrderRouter submissions and enforces book-level halt checks, but it does not
own QMT connection setup or scheduling. GoingMerry remains the private runtime
that wires those dependencies on the live host.
"""
from __future__ import annotations

import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol

from echolon.panel import PanelData
from echolon.portfolio import BookState, TargetBook


class OrderRouterLike(Protocol):
    """Small OrderRouter surface needed by the book executor."""

    def submit_order(
        self,
        *,
        intent: str,
        symbol: str,
        volume: int,
        slot_id: str,
        intended_price: float | None = None,
    ) -> Any: ...

    def trip_circuit(self, reason: str) -> None: ...


@dataclass(frozen=True)
class DiffOrder:
    instrument: str
    symbol: str
    intent: str
    volume: int


@dataclass(frozen=True)
class RiskCheckResult:
    halt: bool
    reason: str = ""
    metrics: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class BookRunResult:
    halted: bool
    risk: RiskCheckResult
    target: TargetBook | None
    orders: list[DiffOrder]


class TargetExecutor:
    """Translate target lots into signed order-router intents."""

    def __init__(
        self,
        *,
        router: OrderRouterLike,
        book_id: str,
        symbol_map: Mapping[str, str],
    ) -> None:
        self.router = router
        self.book_id = book_id
        self.symbol_map = {key.lower(): value for key, value in symbol_map.items()}

    def execute(
        self,
        target: TargetBook,
        *,
        current_lots: Mapping[str, int],
    ) -> list[DiffOrder]:
        """Submit only the lot deltas required to move current book to target.

        Reversals are decomposed into an exit order followed by an entry order so
        live records preserve intent-specific costs and close-today treatment.
        """
        current = {key.lower(): int(value) for key, value in current_lots.items()}
        instruments = sorted(set(current) | {key.lower() for key in target.targets})
        submitted: list[DiffOrder] = []
        for instrument in instruments:
            before = current.get(instrument, 0)
            after = int(target.targets.get(instrument, 0))
            if before == after:
                continue
            submitted.extend(self._orders_for_diff(instrument, before, after))
        for order in submitted:
            self.router.submit_order(
                intent=order.intent,
                symbol=order.symbol,
                volume=order.volume,
                slot_id=self.book_id,
            )
        return submitted

    def _orders_for_diff(self, instrument: str, before: int, after: int) -> list[DiffOrder]:
        symbol = self._symbol_for(instrument)
        orders: list[DiffOrder] = []
        if before > 0 and after <= 0:
            orders.append(DiffOrder(instrument, symbol, "EXIT_LONG", before))
        if before < 0 and after >= 0:
            orders.append(DiffOrder(instrument, symbol, "EXIT_SHORT", abs(before)))
        if after > 0:
            entry_volume = after if before <= 0 else after - before
            if entry_volume > 0:
                orders.append(DiffOrder(instrument, symbol, "ENTRY_LONG", entry_volume))
        if after < 0:
            entry_volume = abs(after) if before >= 0 else abs(after) - abs(before)
            if entry_volume > 0:
                orders.append(DiffOrder(instrument, symbol, "ENTRY_SHORT", entry_volume))
        return orders

    def _symbol_for(self, instrument: str) -> str:
        try:
            return self.symbol_map[instrument]
        except KeyError as exc:
            raise KeyError(f"missing live symbol for instrument {instrument}") from exc


class BookRiskOverlay:
    """Binding book-level risk checks that trip the shared order router."""

    def __init__(
        self,
        *,
        max_drawdown_pct_of_equity: float,
        router: OrderRouterLike,
        peak_equity_rmb: float | None = None,
    ) -> None:
        if max_drawdown_pct_of_equity <= 0:
            raise ValueError("max_drawdown_pct_of_equity must be positive")
        self.max_drawdown_pct_of_equity = float(max_drawdown_pct_of_equity)
        self.router = router
        self.peak_equity_rmb = float(peak_equity_rmb) if peak_equity_rmb is not None else None

    def check(self, book: BookState) -> RiskCheckResult:
        equity = float(book.equity_rmb)
        if self.peak_equity_rmb is None or equity > self.peak_equity_rmb:
            self.peak_equity_rmb = equity
        peak = self.peak_equity_rmb
        drawdown_pct = ((peak - equity) / peak * 100.0) if peak else math.inf
        metrics = {"equity_rmb": equity, "peak_equity_rmb": peak, "drawdown_pct": drawdown_pct}
        if drawdown_pct >= self.max_drawdown_pct_of_equity:
            reason = "book_drawdown"
            self.router.trip_circuit(
                f"{reason}: {drawdown_pct:.2f}% > {self.max_drawdown_pct_of_equity:.2f}%"
            )
            return RiskCheckResult(halt=True, reason=reason, metrics=metrics)
        return RiskCheckResult(halt=False, metrics=metrics)


class BookRunner:
    """One-cycle coordinator for the bundle-era live book path."""

    def __init__(
        self,
        *,
        book_id: str,
        strategy: Callable[[Any, BookState], TargetBook],
        executor: TargetExecutor,
        risk_overlay: BookRiskOverlay,
    ) -> None:
        self.book_id = book_id
        self.strategy = strategy
        self.executor = executor
        self.risk_overlay = risk_overlay

    def run_once(
        self,
        *,
        view: Any,
        book: BookState,
        current_lots: Mapping[str, int],
    ) -> BookRunResult:
        risk = self.risk_overlay.check(book)
        if risk.halt:
            return BookRunResult(halted=True, risk=risk, target=None, orders=[])
        target = self.strategy(view, book)
        orders = self.executor.execute(target, current_lots=current_lots)
        return BookRunResult(halted=False, risk=risk, target=target, orders=orders)


def load_live_panel_view(snapshot_dir: Any, date: Any) -> Any:
    """Load today's live view through the exact immutable PanelData contract."""
    return PanelData.load(snapshot_dir).view(date)
