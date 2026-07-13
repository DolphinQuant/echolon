"""Portfolio constructor pipeline."""
from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Mapping
from typing import Literal

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field

from echolon.panel import PanelView

from .models import BookRiskSnapshot, BookState, InstrumentRebalance, RebalanceRecord, TargetBook


class ConstructorConfig(BaseModel):
    """Capital-relative constructor configuration.

    Percent fields use 0-100 units. No RMB capital constants belong here.
    """

    model_config = ConfigDict(extra="forbid")

    vol_target_ann_pct: float
    sector_caps_pct: dict[str, float]
    max_margin_utilization_pct: float
    min_abs_score_for_position: float
    sizing_mode: Literal["implementation", "research"] = "implementation"
    rebalance_band_lots: float = Field(default=0.0, ge=0.0)
    long_only: bool = False
    max_weight_per_name_pct: float | None = None


class Constructor:
    """Convert blended scores into integer target lots."""

    def __init__(self, config: ConstructorConfig) -> None:
        self.config = config

    def construct(
        self,
        *,
        view: PanelView,
        book: BookState,
        blended_scores: Mapping[str, float],
        raw_scores: Mapping[str, Mapping[str, float | None]],
    ) -> tuple[TargetBook, RebalanceRecord]:
        rows: dict[str, InstrumentRebalance] = {}
        lots_float: dict[str, float] = {}
        effective_scores = {
            instrument: max(float(score), 0.0) if self.config.long_only else float(score)
            for instrument, score in blended_scores.items()
        }
        denom = sum(abs(score) for score in effective_scores.values())
        for instrument, blended in effective_scores.items():
            bars = view.bars(instrument, 64)
            meta = view.meta(instrument)
            if bars.empty:
                vol_ann = 0.0
                pre_round = 0.0
            else:
                price = _raw_price(bars.iloc[-1], "settle")
                vol_ann = _annualized_vol(bars["settle"])
            if bars.empty or denom <= 1e-12 or vol_ann <= 0.0:
                pre_round = 0.0
            else:
                notional = (
                    book.equity_rmb
                    * self.config.vol_target_ann_pct
                    / 100.0
                    * float(blended)
                    / (vol_ann * denom)
                )
                pre_round = notional / (price * float(meta.multiplier))
            if abs(float(blended)) < self.config.min_abs_score_for_position:
                pre_round = 0.0
            lots_float[instrument] = pre_round
            rows[instrument] = InstrumentRebalance(
                raw_scores=dict(raw_scores.get(instrument, {})),
                blended=float(blended),
                vol_ann=vol_ann,
                pre_round_lots=pre_round,
                post_round_lots=0,
                caps_applied=[],
            )

        self._pin_suspended_positions(view, book, lots_float, rows)
        self._apply_sector_caps(view, book, lots_float, rows)
        self._apply_per_name_cap(view, book, lots_float, rows)
        self._apply_margin_cap(view, book, lots_float, rows)

        if self.config.sizing_mode == "research":
            final_targets = {instrument: float(lots) for instrument, lots in lots_float.items()}
        else:
            final_targets = {
                instrument: _toward_zero_lot(lots, float(view.meta(instrument).min_order_size))
                for instrument, lots in lots_float.items()
            }
        final_targets = self._apply_rebalance_band(view, book, final_targets, rows)
        for instrument, lots in final_targets.items():
            rows[instrument].post_round_lots = lots
        return (
            TargetBook(date=view.date, targets=final_targets),
            RebalanceRecord(date=view.date, instruments=rows),
        )

    def _apply_rebalance_band(
        self,
        view: PanelView,
        book: BookState,
        targets: dict[str, float],
        rows: dict[str, InstrumentRebalance],
    ) -> dict[str, float]:
        """Hold small same-direction target changes to reduce churn.

        The band deliberately does not block exits, sign flips, or cap-driven
        de-risking. A proposed banded book must still pass current sector and
        margin caps, so stale positions cannot be preserved by accident.
        """
        band = float(self.config.rebalance_band_lots)
        if band <= 0.0:
            return targets
        banded = dict(targets)
        for instrument, target in targets.items():
            position = book.positions.get(instrument)
            current = 0.0 if position is None else float(position.lots)
            if current == 0.0 or target == 0.0:
                continue
            if _sign(current) != _sign(target):
                continue
            if abs(target) < abs(current):
                continue
            if abs(float(target) - current) > band:
                continue
            banded[instrument] = current
        if banded == targets or not self._targets_within_caps(view, book, banded):
            return targets
        for instrument, target in targets.items():
            after = banded[instrument]
            if after == target:
                continue
            rows[instrument].caps_applied.append(
                {
                    "cap": "rebalance_band_lots",
                    "before": float(target),
                    "after": float(after),
                }
            )
        return banded

    def _targets_within_caps(
        self,
        view: PanelView,
        book: BookState,
        targets: Mapping[str, float],
    ) -> bool:
        risk = self.book_risk(view, book, targets)
        if risk.margin_utilization_pct > self.config.max_margin_utilization_pct + 1e-9:
            return False
        for sector, exposure in risk.sector_gross_notional_pct.items():
            cap = self.config.sector_caps_pct.get(sector)
            if cap is not None and exposure > cap + 1e-9:
                return False
        return True

    def book_risk(
        self,
        view: PanelView,
        book: BookState,
        targets: Mapping[str, float],
    ) -> BookRiskSnapshot:
        gross_by_sector: dict[str, float] = defaultdict(float)
        margin = 0.0
        gross = 0.0
        net = 0.0
        for instrument, lots in targets.items():
            if lots == 0:
                continue
            bars = view.bars(instrument, 1)
            if bars.empty:
                continue
            bar = bars.iloc[-1]
            price = _raw_price(bar, "settle")
            meta = view.meta(instrument)
            notional = lots * price * float(meta.multiplier)
            margin += abs(notional) * float(meta.margin_rate)
            gross += abs(notional)
            net += notional
            gross_by_sector[meta.sector] += abs(notional)
        equity = book.equity_rmb
        return BookRiskSnapshot(
            margin_used_rmb=margin,
            margin_utilization_pct=margin / equity * 100.0 if equity else math.inf,
            gross_exposure_pct=gross / equity * 100.0 if equity else math.inf,
            net_exposure_pct=net / equity * 100.0 if equity else math.inf,
            sector_gross_notional_pct={
                sector: value / equity * 100.0 if equity else math.inf
                for sector, value in gross_by_sector.items()
            },
        )

    def _apply_sector_caps(
        self,
        view: PanelView,
        book: BookState,
        lots_float: dict[str, float],
        rows: dict[str, InstrumentRebalance],
    ) -> None:
        sector_to_instruments: dict[str, list[str]] = defaultdict(list)
        sector_gross: dict[str, float] = defaultdict(float)
        for instrument, lots in lots_float.items():
            meta = view.meta(instrument)
            bars = view.bars(instrument, 1)
            if bars.empty:
                continue
            price = _raw_price(bars.iloc[-1], "settle")
            notional = abs(lots) * price * float(meta.multiplier)
            sector_to_instruments[meta.sector].append(instrument)
            sector_gross[meta.sector] += notional
        for sector, gross in sector_gross.items():
            cap_pct = self.config.sector_caps_pct.get(sector)
            if cap_pct is None:
                continue
            cap_rmb = book.equity_rmb * cap_pct / 100.0
            if gross <= cap_rmb or gross == 0.0:
                continue
            scale = cap_rmb / gross
            for instrument in sector_to_instruments[sector]:
                before = lots_float[instrument]
                lots_float[instrument] *= scale
                rows[instrument].caps_applied.append(
                    {"cap": f"sector:{sector}", "before": before, "after": lots_float[instrument]}
                )

    def _apply_margin_cap(
        self,
        view: PanelView,
        book: BookState,
        lots_float: dict[str, float],
        rows: dict[str, InstrumentRebalance],
    ) -> None:
        margin = 0.0
        for instrument, lots in lots_float.items():
            meta = view.meta(instrument)
            bars = view.bars(instrument, 1)
            if bars.empty:
                continue
            price = _raw_price(bars.iloc[-1], "settle")
            margin += abs(lots) * price * float(meta.multiplier) * float(meta.margin_rate)
        cap_rmb = book.equity_rmb * self.config.max_margin_utilization_pct / 100.0
        if margin <= cap_rmb or margin == 0.0:
            return
        scale = cap_rmb / margin
        for instrument in lots_float:
            before = lots_float[instrument]
            lots_float[instrument] *= scale
            rows[instrument].caps_applied.append(
                {"cap": "margin", "before": before, "after": lots_float[instrument]}
            )

    def _apply_per_name_cap(
        self,
        view: PanelView,
        book: BookState,
        lots_float: dict[str, float],
        rows: dict[str, InstrumentRebalance],
    ) -> None:
        cap_pct = self.config.max_weight_per_name_pct
        if cap_pct is None:
            return
        cap_rmb = book.equity_rmb * cap_pct / 100.0
        for instrument, lots in lots_float.items():
            bars = view.bars(instrument, 1)
            if bars.empty:
                continue
            meta = view.meta(instrument)
            price = _raw_price(bars.iloc[-1], "settle")
            notional = abs(lots) * price * float(meta.multiplier)
            if notional <= cap_rmb or notional == 0.0:
                continue
            before = lots_float[instrument]
            lots_float[instrument] *= cap_rmb / notional
            rows[instrument].caps_applied.append(
                {"cap": "per_name_weight", "before": before, "after": lots_float[instrument]}
            )

    def _pin_suspended_positions(
        self,
        view: PanelView,
        book: BookState,
        targets: dict[str, float],
        rows: dict[str, InstrumentRebalance],
    ) -> None:
        for instrument, target in list(targets.items()):
            bars = view.bars(instrument, 1)
            if bars.empty or float(bars.iloc[-1].get("suspended", 0.0)) != 1.0:
                continue
            position = book.positions.get(instrument)
            held = 0.0 if position is None else float(position.lots)
            targets[instrument] = held
            rows[instrument].caps_applied.append(
                {"cap": "suspended_hold", "before": float(target), "after": held}
            )


def _annualized_vol(settles: pd.Series) -> float:
    returns = pd.to_numeric(settles, errors="coerce").pct_change().dropna()
    if len(returns) < 2:
        return 0.0
    return float(returns.std(ddof=1) * math.sqrt(252.0))


def _toward_zero(value: float) -> int:
    return math.ceil(value) if value < 0 else math.floor(value)


def _toward_zero_lot(value: float, min_order_size: float) -> int:
    if min_order_size <= 0:
        raise ValueError("min_order_size must be positive")
    lots = _toward_zero(value / min_order_size)
    return int(lots * min_order_size)


def _sign(value: float) -> int:
    return 1 if value > 0 else -1


def _raw_price(row: pd.Series, column: str) -> float:
    raw_column = f"{column}_raw"
    if raw_column in row:
        return float(row[raw_column])
    return float(row[column])
