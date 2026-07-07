"""Panel snapshot quality checks."""
from __future__ import annotations

import datetime as dt
import re

import pandas as pd

from .models import QCCheck, QCReport


def _contract_month(contract: str) -> int | None:
    match = re.search(r"(\d{4})", str(contract))
    if match is None:
        return None
    return int(match.group(1))


def _add_check(
    checks: list[QCCheck],
    *,
    check_id: str,
    severity: str,
    message: str,
    instrument: str | None,
    date: dt.date | None,
    value: float | None = None,
) -> None:
    checks.append(
        QCCheck(
            check_id=check_id,
            severity=severity,
            message=message,
            instrument=instrument,
            date=date,
            value=value,
        )
    )


def run_panel_qc(
    *,
    snapshot: str,
    bars: dict[str, pd.DataFrame],
    curves: dict[str, pd.DataFrame],
) -> QCReport:
    """Run S12 QC checks over in-memory panel data."""
    checks: list[QCCheck] = []
    for instrument, frame in bars.items():
        _check_bars(instrument, frame, checks)
    for instrument, frame in curves.items():
        _check_curves(instrument, frame, checks)

    if any(check.severity == "ERROR" for check in checks):
        status = "FAIL"
    elif checks:
        status = "PASS_WITH_WARNINGS"
    else:
        status = "PASS"
    return QCReport(snapshot=snapshot, status=status, checks=checks)


def _check_bars(instrument: str, frame: pd.DataFrame, checks: list[QCCheck]) -> None:
    required_price_columns = ("open", "high", "low", "close", "settle")
    for date, row in frame.iterrows():
        date_value = date if isinstance(date, dt.date) else pd.Timestamp(date).date()
        for column in required_price_columns:
            value = float(row[column])
            if value <= 0:
                _add_check(
                    checks,
                    check_id="price_positive",
                    severity="ERROR",
                    message=f"{column} must be positive",
                    instrument=instrument,
                    date=date_value,
                    value=value,
                )
        volume = float(row["volume"])
        if volume == 0:
            _add_check(
                checks,
                check_id="volume_nonzero",
                severity="WARN",
                message="volume is zero on a trading day",
                instrument=instrument,
                date=date_value,
                value=volume,
            )
        close = float(row["close"])
        settle = float(row["settle"])
        if close > 0:
            divergence = abs(settle - close) / close
            if divergence > 0.08:
                severity = "ERROR"
            elif divergence > 0.03:
                severity = "WARN"
            else:
                severity = None
            if severity is not None:
                _add_check(
                    checks,
                    check_id="settle_close_divergence",
                    severity=severity,
                    message="settle-close divergence exceeds threshold",
                    instrument=instrument,
                    date=date_value,
                    value=divergence,
                )

    closes = pd.to_numeric(frame["close"], errors="coerce")
    returns = closes.pct_change().dropna().abs()
    for date, value in returns.items():
        date_value = date if isinstance(date, dt.date) else pd.Timestamp(date).date()
        if value > 0.12:
            severity = "ERROR"
        elif value > 0.07:
            severity = "WARN"
        else:
            continue
        _add_check(
            checks,
            check_id="daily_return_threshold",
            severity=severity,
            message="daily absolute return exceeds threshold",
            instrument=instrument,
            date=date_value,
            value=float(value),
        )


def _check_curves(instrument: str, frame: pd.DataFrame, checks: list[QCCheck]) -> None:
    for date, row in frame.iterrows():
        date_value = date if isinstance(date, dt.date) else pd.Timestamp(date).date()
        near_settle = float(row["near_settle"])
        far_settle = float(row["far_settle"])
        if near_settle <= 0 or far_settle <= 0:
            _add_check(
                checks,
                check_id="curve_settle_positive",
                severity="ERROR",
                message="curve settle prices must be positive",
                instrument=instrument,
                date=date_value,
                value=min(near_settle, far_settle),
            )
        near_month = _contract_month(str(row["near_contract"]))
        far_month = _contract_month(str(row["far_contract"]))
        if near_month is not None and far_month is not None and near_month >= far_month:
            _add_check(
                checks,
                check_id="curve_contract_order",
                severity="ERROR",
                message="near contract must expire before far contract",
                instrument=instrument,
                date=date_value,
                value=float(near_month),
            )
