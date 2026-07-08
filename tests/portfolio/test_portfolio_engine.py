from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

import pandas as pd
import pytest
from hypothesis import given, settings, strategies as st

from echolon.panel.models import InstrumentMeta
from echolon.portfolio import (
    BookState,
    Combiner,
    Constructor,
    ConstructorConfig,
    PortfolioStrategy,
    PositionState,
)
from echolon.signals import ScoreVector, SignalEngine


@dataclass(frozen=True)
class _View:
    date: dt.date
    bars_by_instrument: dict[str, pd.DataFrame]
    meta_by_instrument: dict[str, InstrumentMeta]

    def bars(self, instrument: str, lookback: int) -> pd.DataFrame:
        frame = self.bars_by_instrument[instrument]
        return frame.loc[frame.index <= self.date].tail(lookback).copy()

    def meta(self, instrument: str) -> InstrumentMeta:
        return self.meta_by_instrument[instrument]


def _bars(start_price: float = 100.0) -> pd.DataFrame:
    dates = [dt.date(2024, 1, 1) + dt.timedelta(days=index) for index in range(80)]
    prices = [start_price + index for index in range(80)]
    return pd.DataFrame(
        {
            "open": prices,
            "high": [price + 1.0 for price in prices],
            "low": [price - 1.0 for price in prices],
            "close": prices,
            "settle": prices,
            "volume": [1000] * 80,
            "open_interest": [5000] * 80,
            "contract": ["T2401"] * 80,
        },
        index=dates,
    )


def _meta(instrument: str, sector: str) -> InstrumentMeta:
    return InstrumentMeta(
        instrument_id=instrument,
        sector=sector,
        multiplier=10.0,
        tick=1.0,
        margin_rate=0.10,
        commission=3.0,
        commission_type="per_contract",
        close_today_commission=None,
        currency="RMB",
    )


def _view() -> _View:
    return _View(
        date=dt.date(2024, 3, 20),
        bars_by_instrument={"al": _bars(100.0), "cu": _bars(200.0)},
        meta_by_instrument={"al": _meta("al", "base"), "cu": _meta("cu", "base")},
    )


def _book(equity: float = 100_000.0) -> BookState:
    return BookState(date=dt.date(2024, 3, 20), equity_rmb=equity, cash_rmb=equity, margin_used_rmb=0.0)


def test_combiner_renormalizes_weights_for_missing_scores():
    vectors = [
        ScoreVector(signal_id="a", family="tsmom", date=dt.date(2024, 1, 1), scores={"al": 1.0, "cu": None}),
        ScoreVector(signal_id="b", family="carry", date=dt.date(2024, 1, 1), scores={"al": -1.0, "cu": 2.0}),
    ]

    blended = Combiner({"a": 0.25, "b": 0.75}).combine(vectors, instruments=["al", "cu"])

    assert blended == {"al": -0.5, "cu": 2.0}


def test_constructor_zero_score_book_is_flat():
    constructor = Constructor(
        ConstructorConfig(
            vol_target_ann_pct=10.0,
            sector_caps_pct={"base": 50.0},
            max_margin_utilization_pct=20.0,
            min_abs_score_for_position=0.5,
        )
    )

    target, record = constructor.construct(
        view=_view(),
        book=_book(),
        blended_scores={"al": 0.0, "cu": 0.0},
        raw_scores={"al": {}, "cu": {}},
    )

    assert target.targets == {"al": 0, "cu": 0}
    assert all(row.post_round_lots == 0 for row in record.instruments.values())


def test_constructor_sets_zero_when_instrument_has_no_visible_bars():
    view = _View(
        date=dt.date(2024, 3, 20),
        bars_by_instrument={"al": _bars(100.0), "cu": _bars(200.0).iloc[0:0]},
        meta_by_instrument={"al": _meta("al", "base"), "cu": _meta("cu", "base")},
    )
    constructor = Constructor(
        ConstructorConfig(
            vol_target_ann_pct=10.0,
            sector_caps_pct={"base": 50.0},
            max_margin_utilization_pct=20.0,
            min_abs_score_for_position=0.0,
        )
    )

    target, record = constructor.construct(
        view=view,
        book=_book(),
        blended_scores={"al": 1.0, "cu": 1.0},
        raw_scores={"al": {}, "cu": {}},
    )

    assert target.targets["cu"] == 0
    assert record.instruments["cu"].vol_ann == 0.0


@given(
    al_score=st.floats(min_value=-3.0, max_value=3.0, allow_nan=False, allow_infinity=False),
    cu_score=st.floats(min_value=-3.0, max_value=3.0, allow_nan=False, allow_infinity=False),
)
@settings(max_examples=50)
def test_constructor_never_exceeds_margin_cap_after_rounding(al_score: float, cu_score: float):
    constructor = Constructor(
        ConstructorConfig(
            vol_target_ann_pct=80.0,
            sector_caps_pct={"base": 100.0},
            max_margin_utilization_pct=5.0,
            min_abs_score_for_position=0.0,
        )
    )

    target, _ = constructor.construct(
        view=_view(),
        book=_book(),
        blended_scores={"al": al_score, "cu": cu_score},
        raw_scores={"al": {}, "cu": {}},
    )

    risk = constructor.book_risk(_view(), _book(), target.targets)
    assert risk.margin_utilization_pct <= 5.0 + 1e-9


@given(score=st.floats(min_value=-3.0, max_value=3.0, allow_nan=False, allow_infinity=False))
@settings(max_examples=50)
def test_constructor_never_exceeds_sector_cap_after_rounding(score: float):
    constructor = Constructor(
        ConstructorConfig(
            vol_target_ann_pct=80.0,
            sector_caps_pct={"base": 3.0},
            max_margin_utilization_pct=100.0,
            min_abs_score_for_position=0.0,
        )
    )

    target, _ = constructor.construct(
        view=_view(),
        book=_book(),
        blended_scores={"al": score, "cu": score},
        raw_scores={"al": {}, "cu": {}},
    )

    risk = constructor.book_risk(_view(), _book(), target.targets)
    assert risk.sector_gross_notional_pct.get("base", 0.0) <= 3.0 + 1e-9


def test_portfolio_strategy_composes_engines_combiner_and_constructor():
    class FixedSignal(SignalEngine):
        signal_id = "fixed_v1"
        family = "tsmom"
        params = {}
        data_requirements = {}

        def compute(self, view):
            return ScoreVector(
                signal_id=self.signal_id,
                family=self.family,
                date=view.date,
                scores={"al": 1.0, "cu": None},
            )

    strategy = PortfolioStrategy(
        engines=[FixedSignal()],
        blend={"fixed_v1": 1.0},
        constructor_cfg=ConstructorConfig(
            vol_target_ann_pct=10.0,
            sector_caps_pct={"base": 50.0},
            max_margin_utilization_pct=20.0,
            min_abs_score_for_position=0.0,
        ),
    )

    target, record = strategy.rebalance(_view(), _book())

    assert set(target.targets) == {"al", "cu"}
    assert target.targets["al"] > 0
    assert target.targets["cu"] == 0
    assert record.instruments["al"].raw_scores == {"fixed_v1": 1.0}
    assert record.instruments["cu"].raw_scores == {"fixed_v1": None}
