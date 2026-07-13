"""Exchange-true futures expiry and trading-day DTE falsifiers."""
from __future__ import annotations

import datetime as dt

import pandas as pd
import pytest

from echolon.markets.expiry import days_to_expiry, expiry_date
from echolon.markets.shfe.trading_calendar import TradingCalendar


@pytest.fixture
def pinned_shfe_calendar(tmp_path) -> TradingCalendar:
    # The plan defines SHFE "expiry" as the last date a general position may be
    # held before delivery month and mandates delegation to contract_rules.py.
    # Rule source: echolon/markets/shfe/contract_rules.py:get_expiry_date, which
    # is the authoritative in-repo source explicitly pinned by FV2-WP2a D2.
    # These five dates were independently checked against the SHFE sessions in
    # the p2_v4 snapshot (the expected month-end sessions are listed below).
    trading_days = pd.to_datetime(
        [
            "2024-01-31",  # al2402
            "2024-02-29",  # cu2403
            "2024-04-30",  # rb2405
            "2024-09-30",  # zn2410
            "2025-01-27",  # ni2502; Jan 28-31 exchange holiday
            "2025-02-05",
            "2025-02-06",
            "2025-02-07",
            "2025-02-10",
        ]
    )
    path = tmp_path / "shfe_calendar.csv"
    pd.DataFrame({"date": trading_days.strftime("%Y-%m-%d")}).to_csv(path, index=False)
    return TradingCalendar(str(path))


@pytest.mark.parametrize(
    ("contract", "expected"),
    [
        ("al2402", dt.date(2024, 1, 31)),
        ("CU2403", dt.date(2024, 2, 29)),
        ("rb2405", dt.date(2024, 4, 30)),
        ("zn2410", dt.date(2024, 9, 30)),
        ("ni2502", dt.date(2025, 1, 27)),
    ],
)
def test_shfe_expiry_delegates_to_pinned_contract_rule(
    pinned_shfe_calendar: TradingCalendar,
    contract: str,
    expected: dt.date,
) -> None:
    assert expiry_date(contract, "shfe", pinned_shfe_calendar) == expected


def test_expiry_rejects_unloaded_weekend_only_calendar() -> None:
    with pytest.raises(ValueError, match="loaded exchange calendar"):
        expiry_date("cu2403", "SHFE", TradingCalendar())


@pytest.mark.parametrize("exchange", ["CZCE", "DCE", "INE", "UNKNOWN"])
def test_expiry_fails_loudly_for_unpinned_exchange(exchange: str) -> None:
    with pytest.raises(NotImplementedError, match=exchange):
        expiry_date("cu2403", exchange, object())


def test_days_to_expiry_counts_future_trading_sessions_only(
    pinned_shfe_calendar: TradingCalendar,
) -> None:
    assert days_to_expiry(
        "ni2503",
        "SHFE",
        dt.date(2025, 2, 5),
        pinned_shfe_calendar,
    ) == 3
    assert days_to_expiry(
        "ni2503",
        "SHFE",
        dt.date(2025, 2, 10),
        pinned_shfe_calendar,
    ) == 0

