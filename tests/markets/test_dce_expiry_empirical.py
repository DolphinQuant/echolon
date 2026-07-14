"""Offline DCE rule falsifier against the authoritative p2_v4 panel."""

from __future__ import annotations

import datetime as dt
import os
import re
from pathlib import Path

import pandas as pd
import pytest

from echolon.markets.expiry import last_trade_date
from echolon.markets.shfe.trading_calendar import TradingCalendar

DCE_INSTRUMENTS = ("c", "p", "pp", "eg", "jd", "i", "l", "m", "v", "y")


def test_dce_encoded_rule_reproduces_at_least_95pct_empirical_last_trades() -> None:
    snapshot = _snapshot_path()
    if not snapshot.exists():
        pytest.skip(f"real p2_v4 snapshot unavailable: {snapshot}")

    rows = []
    for instrument in DCE_INSTRUMENTS:
        frame = pd.read_csv(
            snapshot / "contracts" / f"{instrument}.csv",
            usecols=["date", "contract"],
        )
        frame["date"] = pd.to_datetime(frame["date"])
        rows.append(frame)
    contracts = pd.concat(rows, ignore_index=True)
    panel_end = contracts["date"].max().date()
    calendar = TradingCalendar()
    calendar._trading_days = set(contracts["date"].dt.date)
    calendar._calendar_loaded = True

    results: list[tuple[str, dt.date, dt.date]] = []
    for contract, group in contracts.groupby("contract"):
        delivery_year, delivery_month = _delivery_month(str(contract))
        # A delivery month still in progress at the panel end is not expired.
        if (delivery_year, delivery_month) >= (panel_end.year, panel_end.month):
            continue
        empirical = group["date"].max().date()
        predicted = last_trade_date(str(contract), "DCE", calendar)
        results.append((str(contract), empirical, predicted))

    matches = sum(empirical == predicted for _, empirical, predicted in results)
    assert len(results) == 1068
    assert matches == 1022
    assert matches / len(results) >= 0.95


def _snapshot_path() -> Path:
    configured = os.environ.get("DOLPHINQUANT_P2_V4_PANEL")
    if configured:
        return Path(configured)
    return (
        Path(__file__).resolve().parents[4]
        / "output_bank/market/panels/p2_v4_shfe_czce_dce_ine"
    )


def _delivery_month(contract: str) -> tuple[int, int]:
    match = re.fullmatch(r"[A-Za-z]+(\d{2})(\d{2})", contract)
    if match is None:
        raise ValueError(f"unexpected DCE contract identifier: {contract}")
    return 2000 + int(match.group(1)), int(match.group(2))
