from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import pandas as pd
import pytest

from echolon.backtest.book import BookBacktestConfig, DailyBookBacktester
from echolon.panel.models import InstrumentMeta
from echolon.portfolio import BookState, RebalanceRecord, TargetBook


class _Panel:
    snapshot_version = "synthetic_book"

    def __init__(self) -> None:
        self.instruments = ["al", "cu"]
        self.calendar = [dt.date(2024, 1, 2) + dt.timedelta(days=i) for i in range(5)]
        self._bars = {
            "al": _bars([19000.0, 19010.0, 19020.0, 19030.0, 19040.0], "al2402"),
            "cu": _bars([70000.0] * 5, "cu2402"),
        }
        self._contracts = {
            instrument: frame.assign(symbol=frame["contract"])
            for instrument, frame in self._bars.items()
        }
        self._meta = {
            "al": InstrumentMeta(
                instrument_id="al",
                sector="base",
                multiplier=5.0,
                tick=0.01,
                margin_rate=0.09,
                commission=3.01,
                commission_type="per_contract",
                close_today_commission=3.01,
                currency="RMB",
            ),
            "cu": InstrumentMeta(
                instrument_id="cu",
                sector="base",
                multiplier=5.0,
                tick=10.0,
                margin_rate=0.09,
                commission=0.00005,
                commission_type="percentage",
                close_today_commission=None,
                currency="RMB",
            ),
        }

    def view(self, date: dt.date):
        return _View(date, self._bars, self._meta, self._contracts)


class _View:
    def __init__(self, date, bars, meta, contracts) -> None:
        self.date = date
        self._bars = bars
        self._meta = meta
        self._contracts = contracts

    def bars(self, instrument: str, lookback: int) -> pd.DataFrame:
        frame = self._bars[instrument]
        return frame.loc[frame.index <= self.date].tail(lookback).copy()

    def contract_bar(self, instrument: str, contract: str):
        frame = self._contracts[instrument]
        rows = frame.loc[frame.index == self.date]
        rows = rows[rows["contract"].astype(str) == str(contract)]
        if rows.empty:
            return None
        return rows.iloc[0].copy()

    def meta(self, instrument: str) -> InstrumentMeta:
        return self._meta[instrument]


class _StaticStrategy:
    def __init__(self, targets: dict[str, int]) -> None:
        self.targets = targets

    def rebalance(self, view, book: BookState):
        return TargetBook(date=view.date, targets=dict(self.targets)), RebalanceRecord(date=view.date, instruments={})


class _DatedStrategy:
    def __init__(self, targets_by_date: dict[dt.date, dict[str, int]]) -> None:
        self.targets_by_date = targets_by_date

    def rebalance(self, view, book: BookState):
        targets = self.targets_by_date.get(view.date, {})
        return TargetBook(date=view.date, targets=dict(targets)), RebalanceRecord(date=view.date, instruments={})


def _bars(prices: list[float], contract: str) -> pd.DataFrame:
    dates = [dt.date(2024, 1, 2) + dt.timedelta(days=i) for i in range(len(prices))]
    return pd.DataFrame(
        {
            "open": prices,
            "high": [price + 1.0 for price in prices],
            "low": [price - 1.0 for price in prices],
            "close": prices,
            "settle": prices,
            "volume": [1000] * len(prices),
            "open_interest": [5000] * len(prices),
            "contract": [contract] * len(prices),
        },
        index=dates,
    )


def test_book_backtester_applies_s11_slippage_and_commission(tmp_path: Path):
    panel = _Panel()
    backtester = DailyBookBacktester(output_dir=tmp_path, slippage_bps=3.0, rebalance_weekday=None)

    result = backtester.run(
        _StaticStrategy({"al": 1, "cu": 1}),
        panel,
        BookBacktestConfig(
            start=dt.date(2024, 1, 2),
            end=dt.date(2024, 1, 6),
            initial_equity_rmb=700_000.0,
            panel_snapshot="synthetic_book",
        ),
    )

    al_trade = next(trade for trade in result.trades if trade.instrument == "al")
    cu_trade = next(trade for trade in result.trades if trade.instrument == "cu")
    assert al_trade.date == dt.date(2024, 1, 3)
    assert al_trade.intended_price == 19010.0
    assert al_trade.fill_price == 19015.7
    assert al_trade.commission_rmb == pytest.approx(3.01, abs=0.01)
    assert cu_trade.commission_rmb == pytest.approx(17.50, abs=0.01)
    assert (tmp_path / "equity_curve.csv").is_file()
    assert (tmp_path / "trades.csv").is_file()
    assert json.loads((tmp_path / "summary.json").read_text())["determinism_hash"] == result.summary.determinism_hash


def test_book_backtester_forced_liquidation_event(tmp_path: Path):
    panel = _Panel()
    backtester = DailyBookBacktester(output_dir=tmp_path, slippage_bps=0.0, rebalance_weekday=None)

    result = backtester.run(
        _StaticStrategy({"cu": 100}),
        panel,
        BookBacktestConfig(
            start=dt.date(2024, 1, 2),
            end=dt.date(2024, 1, 6),
            initial_equity_rmb=10_000.0,
            panel_snapshot="synthetic_book",
        ),
    )

    assert result.events
    assert result.events[0]["type"] == "forced_liquidation"
    assert result.equity_curve[-1].margin_used_rmb == 0.0


def test_book_backtester_artifacts_are_deterministic(tmp_path: Path):
    panel = _Panel()
    config = BookBacktestConfig(
        start=dt.date(2024, 1, 2),
        end=dt.date(2024, 1, 6),
        initial_equity_rmb=700_000.0,
        panel_snapshot="synthetic_book",
    )
    first_dir = tmp_path / "first"
    second_dir = tmp_path / "second"

    first = DailyBookBacktester(output_dir=first_dir, slippage_bps=3.0, rebalance_weekday=None).run(
        _StaticStrategy({"al": 1, "cu": -1}),
        panel,
        config,
    )
    second = DailyBookBacktester(output_dir=second_dir, slippage_bps=3.0, rebalance_weekday=None).run(
        _StaticStrategy({"al": 1, "cu": -1}),
        panel,
        config,
    )

    assert first.summary.determinism_hash == second.summary.determinism_hash
    for name in ("equity_curve.csv", "trades.csv", "daily_returns.csv", "events.jsonl", "summary.json"):
        assert (first_dir / name).read_bytes() == (second_dir / name).read_bytes()


def test_book_backtester_roll_preserves_accrued_contract_pnl(tmp_path: Path):
    class RollingPanel(_Panel):
        def __init__(self) -> None:
            super().__init__()
            dates = self.calendar
            self._bars["al"] = pd.DataFrame(
                {
                    "open": [100.0, 100.0, 200.0, 200.0, 200.0],
                    "high": [100.0, 100.0, 200.0, 200.0, 200.0],
                    "low": [100.0, 100.0, 200.0, 200.0, 200.0],
                    "close": [100.0, 100.0, 200.0, 200.0, 200.0],
                    "settle": [100.0, 100.0, 200.0, 200.0, 200.0],
                    "volume": [1000] * 5,
                    "open_interest": [5000] * 5,
                    "contract": ["AL2401", "AL2401", "AL2402", "AL2402", "AL2402"],
                },
                index=dates,
            )
            self._contracts["al"] = pd.DataFrame(
                [
                    {"symbol": "AL2401", "contract": "AL2401", "open": 100.0, "high": 100.0, "low": 100.0, "close": 100.0, "settle": 100.0, "volume": 1000, "open_interest": 5000},
                    {"symbol": "AL2401", "contract": "AL2401", "open": 100.0, "high": 100.0, "low": 100.0, "close": 100.0, "settle": 100.0, "volume": 1000, "open_interest": 5000},
                    {"symbol": "AL2401", "contract": "AL2401", "open": 110.0, "high": 110.0, "low": 110.0, "close": 110.0, "settle": 110.0, "volume": 1000, "open_interest": 5000},
                    {"symbol": "AL2402", "contract": "AL2402", "open": 200.0, "high": 200.0, "low": 200.0, "close": 200.0, "settle": 200.0, "volume": 1000, "open_interest": 5000},
                    {"symbol": "AL2402", "contract": "AL2402", "open": 200.0, "high": 200.0, "low": 200.0, "close": 200.0, "settle": 200.0, "volume": 1000, "open_interest": 5000},
                ],
                index=[dates[0], dates[1], dates[2], dates[2], dates[3]],
            )
            self._meta["al"] = self._meta["al"].model_copy(update={"commission": 0.0, "close_today_commission": 0.0})

    result = DailyBookBacktester(
        output_dir=tmp_path,
        slippage_bps=0.0,
        rebalance_weekday=None,
    ).run(
        _StaticStrategy({"al": 1}),
        RollingPanel(),
        BookBacktestConfig(
            start=dt.date(2024, 1, 2),
            end=dt.date(2024, 1, 6),
            initial_equity_rmb=100_000.0,
            panel_snapshot="rolling_synthetic",
        ),
    )

    assert [trade.contract for trade in result.trades] == ["AL2401", "AL2401", "AL2402"]
    assert result.trades[1].realized_pnl_rmb == pytest.approx(50.0)
    assert result.equity_curve[-1].equity_rmb == pytest.approx(100_050.0)


def test_book_backtester_closes_held_contract_when_flattening_on_roll_date(tmp_path: Path):
    class RollingPanel(_Panel):
        def __init__(self) -> None:
            super().__init__()
            dates = self.calendar
            self._bars["al"] = pd.DataFrame(
                {
                    "open": [100.0, 100.0, 200.0, 200.0, 200.0],
                    "high": [100.0, 100.0, 200.0, 200.0, 200.0],
                    "low": [100.0, 100.0, 200.0, 200.0, 200.0],
                    "close": [100.0, 100.0, 200.0, 200.0, 200.0],
                    "settle": [100.0, 100.0, 200.0, 200.0, 200.0],
                    "volume": [1000] * 5,
                    "open_interest": [5000] * 5,
                    "contract": ["AL2401", "AL2401", "AL2402", "AL2402", "AL2402"],
                },
                index=dates,
            )
            self._contracts["al"] = pd.DataFrame(
                [
                    {"symbol": "AL2401", "contract": "AL2401", "open": 100.0, "high": 100.0, "low": 100.0, "close": 100.0, "settle": 100.0, "volume": 1000, "open_interest": 5000},
                    {"symbol": "AL2401", "contract": "AL2401", "open": 100.0, "high": 100.0, "low": 100.0, "close": 100.0, "settle": 100.0, "volume": 1000, "open_interest": 5000},
                    {"symbol": "AL2401", "contract": "AL2401", "open": 110.0, "high": 110.0, "low": 110.0, "close": 110.0, "settle": 110.0, "volume": 1000, "open_interest": 5000},
                    {"symbol": "AL2402", "contract": "AL2402", "open": 200.0, "high": 200.0, "low": 200.0, "close": 200.0, "settle": 200.0, "volume": 1000, "open_interest": 5000},
                ],
                index=[dates[0], dates[1], dates[2], dates[2]],
            )
            self._meta["al"] = self._meta["al"].model_copy(update={"commission": 0.0, "close_today_commission": 0.0})

    result = DailyBookBacktester(
        output_dir=tmp_path,
        slippage_bps=0.0,
        rebalance_weekday=None,
    ).run(
        _DatedStrategy(
            {
                dt.date(2024, 1, 2): {"al": 1},
                dt.date(2024, 1, 3): {"al": 0},
            }
        ),
        RollingPanel(),
        BookBacktestConfig(
            start=dt.date(2024, 1, 2),
            end=dt.date(2024, 1, 6),
            initial_equity_rmb=100_000.0,
            panel_snapshot="rolling_synthetic",
        ),
    )

    assert [trade.contract for trade in result.trades] == ["AL2401", "AL2401"]
    assert [trade.position_after for trade in result.trades] == [1, 0]
    assert result.trades[1].realized_pnl_rmb == pytest.approx(50.0)
    assert result.equity_curve[-1].equity_rmb == pytest.approx(100_050.0)
