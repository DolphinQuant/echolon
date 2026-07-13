"""Exchange-backed futures expiry and trading-day distance utilities."""
from __future__ import annotations

import datetime as dt

from echolon.markets.shfe import contract_rules as shfe_contract_rules
from echolon.markets.shfe.trading_calendar import TradingCalendar


def _require_loaded_calendar(calendar: TradingCalendar) -> None:
    """Reject the SHFE calendar's weekend-only approximation mode."""
    if not isinstance(calendar, TradingCalendar) or not calendar.is_loaded:
        raise ValueError("expiry calculation requires a loaded exchange calendar")


def expiry_date(
    contract: str,
    exchange: str,
    calendar: TradingCalendar,
) -> dt.date:
    """Return the exchange-rule expiry date for ``contract``.

    SHFE delegates to its canonical in-repository contract-rule module and
    requires a loaded exchange calendar. Exchanges without a pinned rule fail
    with :class:`NotImplementedError`; this function never falls back to a
    weekday or calendar-day approximation.
    """
    exchange_id = exchange.upper()
    if exchange_id != "SHFE":
        raise NotImplementedError(
            f"{exchange_id} expiry rule is not authoritatively pinned"
        )
    _require_loaded_calendar(calendar)
    return shfe_contract_rules.get_expiry_date(contract, calendar)


def days_to_expiry(
    contract: str,
    exchange: str,
    asof: dt.date,
    calendar: TradingCalendar,
) -> int:
    """Return trading sessions after ``asof`` through contract expiry.

    The result is zero on expiry. Dates after expiry return a negative count of
    trading sessions from expiry through ``asof``. Unsupported exchanges and
    unloaded calendars fail exactly as :func:`expiry_date` does.
    """
    expiry = expiry_date(contract, exchange, calendar)
    if asof == expiry:
        return 0
    if asof < expiry:
        return sum(
            calendar.is_trading_day(day)
            for day in _dates_between(asof, expiry)
        )
    return -sum(
        calendar.is_trading_day(day)
        for day in _dates_between(expiry, asof)
    )


def _dates_between(start: dt.date, end: dt.date) -> list[dt.date]:
    """Return calendar dates in ``(start, end]``."""
    return [
        start + dt.timedelta(days=offset)
        for offset in range(1, (end - start).days + 1)
    ]
