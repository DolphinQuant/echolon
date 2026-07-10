"""Two-cadence sleeve composition for one book.

A slow sleeve (e.g. monthly carry/momentum core) and a fast sleeve (e.g.
weekly reversal) each run their own PortfolioStrategy on their own capital
fraction; the book trades the SUM of their target lots on the fast cadence.
Weekly rebalancing of slow signals is cost suicide (their targets barely move
week to week but the churn pays full costs), while monthly rebalancing of
fast signals destroys their information — so each sleeve keeps its own clock:
the fast sleeve recomputes every call, the slow sleeve recomputes every
``slow_interval_weeks`` and holds its last targets in between, exactly as a
standalone slow book would hold positions.
"""
from __future__ import annotations

import datetime as dt

from echolon.panel import PanelView

from .models import BookState, InstrumentRebalance, PositionState, RebalanceRecord, TargetBook
from .strategy import PortfolioStrategy


class TwoSleeveStrategy:
    """Compose a slow and a fast PortfolioStrategy into one target book."""

    def __init__(
        self,
        *,
        slow: PortfolioStrategy,
        fast: PortfolioStrategy,
        slow_capital_fraction: float,
        fast_capital_fraction: float,
        slow_interval_weeks: int = 4,
    ) -> None:
        if slow_capital_fraction <= 0.0 or fast_capital_fraction <= 0.0:
            raise ValueError("sleeve capital fractions must be positive")
        if slow_capital_fraction + fast_capital_fraction > 1.0 + 1e-9:
            raise ValueError("sleeve capital fractions must not exceed 1.0 combined")
        if slow_interval_weeks < 1:
            raise ValueError("slow_interval_weeks must be >= 1")
        slow_ids = set(slow.combiner.weights)
        fast_ids = set(fast.combiner.weights)
        overlap = slow_ids & fast_ids
        if overlap:
            raise ValueError(
                f"sleeves must not share signal ids (ambiguous records): {sorted(overlap)}"
            )
        self.slow = slow
        self.fast = fast
        self.slow_capital_fraction = float(slow_capital_fraction)
        self.fast_capital_fraction = float(fast_capital_fraction)
        self.slow_interval_weeks = int(slow_interval_weeks)
        self._anchor: dt.date | None = None
        self._slow_targets: dict[str, float] = {}
        self._slow_record: RebalanceRecord | None = None

    def rebalance(self, view: PanelView, book: BookState) -> tuple[TargetBook, RebalanceRecord]:
        if self._anchor is None:
            self._anchor = view.date
        weeks_since_anchor = (view.date - self._anchor).days // 7
        slow_due = (
            self._slow_record is None
            or weeks_since_anchor % self.slow_interval_weeks == 0
        )

        if slow_due:
            slow_book = _sleeve_book(book, self.slow_capital_fraction, self._slow_targets)
            slow_target, slow_record = self.slow.rebalance(view, slow_book)
            self._slow_targets = dict(slow_target.targets)
            self._slow_record = slow_record

        fast_book = _sleeve_book(book, self.fast_capital_fraction, {})
        fast_target, fast_record = self.fast.rebalance(view, fast_book)

        instruments = sorted(set(self._slow_targets) | set(fast_target.targets))
        combined = {
            instrument: float(self._slow_targets.get(instrument, 0.0))
            + float(fast_target.targets.get(instrument, 0.0))
            for instrument in instruments
        }
        record = RebalanceRecord(
            date=view.date,
            instruments={
                instrument: _merged_row(
                    instrument,
                    slow_record=self._slow_record,
                    fast_record=fast_record,
                    slow_lots=float(self._slow_targets.get(instrument, 0.0)),
                    combined_lots=combined[instrument],
                    slow_refreshed=slow_due,
                    slow_fraction=self.slow_capital_fraction,
                    fast_fraction=self.fast_capital_fraction,
                )
                for instrument in instruments
            },
        )
        return TargetBook(date=view.date, targets=combined), record


def _sleeve_book(
    book: BookState,
    fraction: float,
    sleeve_lots: dict[str, float],
) -> BookState:
    """Present the sleeve with its capital share and its OWN last targets.

    The constructor's rebalance band compares new targets against held lots;
    a sleeve must band against what it asked for last time, not against the
    combined book (which contains the other sleeve's positions).
    """
    return BookState(
        date=book.date,
        equity_rmb=book.equity_rmb * fraction,
        cash_rmb=book.cash_rmb * fraction,
        margin_used_rmb=0.0,
        positions={
            instrument: PositionState(lots=lots, avg_price=0.0, contract="", margin_rmb=0.0)
            for instrument, lots in sleeve_lots.items()
            if lots
        },
    )


def _merged_row(
    instrument: str,
    *,
    slow_record: RebalanceRecord | None,
    fast_record: RebalanceRecord,
    slow_lots: float,
    combined_lots: float,
    slow_refreshed: bool,
    slow_fraction: float,
    fast_fraction: float,
) -> InstrumentRebalance:
    slow_row = slow_record.instruments.get(instrument) if slow_record is not None else None
    fast_row = fast_record.instruments.get(instrument)
    raw_scores: dict[str, float | None] = {}
    if slow_row is not None:
        raw_scores.update(slow_row.raw_scores)
    if fast_row is not None:
        raw_scores.update(fast_row.raw_scores)
    slow_blend = slow_row.blended if slow_row is not None else 0.0
    fast_blend = fast_row.blended if fast_row is not None else 0.0
    total_fraction = slow_fraction + fast_fraction
    caps: list[dict[str, float | str]] = []
    if fast_row is not None:
        caps.extend(fast_row.caps_applied)
    if slow_row is not None and slow_refreshed:
        caps.extend(slow_row.caps_applied)
    if not slow_refreshed:
        caps.append({"cap": "slow_sleeve_held", "before": slow_lots, "after": slow_lots})
    return InstrumentRebalance(
        raw_scores=raw_scores,
        blended=(slow_blend * slow_fraction + fast_blend * fast_fraction) / total_fraction,
        vol_ann=fast_row.vol_ann if fast_row is not None else 0.0,
        pre_round_lots=slow_lots + (fast_row.pre_round_lots if fast_row is not None else 0.0),
        post_round_lots=combined_lots,
        caps_applied=caps,
    )
