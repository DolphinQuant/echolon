"""Portfolio constructor pipeline."""
from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Mapping

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
        denom = sum(abs(score) for score in blended_scores.values())
        for instrument, blended in blended_scores.items():
            bars = view.bars(instrument, 64)
            price = float(bars.iloc[-1]["settle"])
            meta = view.meta(instrument)
            vol_ann = _annualized_vol(bars["settle"])
            if denom <= 1e-12 or vol_ann <= 0.0:
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

        self._apply_sector_caps(view, book, lots_float, rows)
        self._apply_margin_cap(view, book, lots_float, rows)

        final_targets = {instrument: _toward_zero(lots) for instrument, lots in lots_float.items()}
        for instrument, lots in final_targets.items():
            rows[instrument].post_round_lots = lots
        return (
            TargetBook(date=view.date, targets=final_targets),
            RebalanceRecord(date=view.date, instruments=rows),
        )

    def book_risk(
        self,
        view: PanelView,
        book: BookState,
        targets: Mapping[str, int],
    ) -> BookRiskSnapshot:
        gross_by_sector: dict[str, float] = defaultdict(float)
        margin = 0.0
        gross = 0.0
        net = 0.0
        for instrument, lots in targets.items():
            if lots == 0:
                continue
            bar = view.bars(instrument, 1).iloc[-1]
            price = float(bar["settle"])
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
            price = float(view.bars(instrument, 1).iloc[-1]["settle"])
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
            price = float(view.bars(instrument, 1).iloc[-1]["settle"])
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


def _annualized_vol(settles: pd.Series) -> float:
    returns = pd.to_numeric(settles, errors="coerce").pct_change().dropna()
    if len(returns) < 2:
        return 0.0
    return float(returns.std(ddof=1) * math.sqrt(252.0))


def _toward_zero(value: float) -> int:
    return math.ceil(value) if value < 0 else math.floor(value)
