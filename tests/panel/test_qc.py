from __future__ import annotations

import datetime as dt

import pandas as pd

from echolon.panel.qc import run_panel_qc


def test_qc_fails_on_zero_price_and_bad_curve_order():
    bars = {
        "al": pd.DataFrame(
            [
                {
                    "open": 19000.0,
                    "high": 19100.0,
                    "low": 18900.0,
                    "close": 19000.0,
                    "settle": 19000.0,
                    "volume": 100,
                    "open_interest": 1000,
                    "contract": "al2402",
                },
                {
                    "open": 0.0,
                    "high": 19100.0,
                    "low": 18900.0,
                    "close": 19020.0,
                    "settle": 19020.0,
                    "volume": 100,
                    "open_interest": 1000,
                    "contract": "al2402",
                },
            ],
            index=[dt.date(2024, 1, 2), dt.date(2024, 1, 3)],
        )
    }
    curves = {
        "al": pd.DataFrame(
            [
                {
                    "near_contract": "al2403",
                    "near_settle": 19010.0,
                    "far_contract": "al2402",
                    "far_settle": 19080.0,
                    "days_between": 30,
                }
            ],
            index=[dt.date(2024, 1, 3)],
        )
    }

    report = run_panel_qc(snapshot="synthetic", bars=bars, curves=curves)

    assert report.schema == "qc/v1"
    assert report.status == "FAIL"
    severities = {check.severity for check in report.checks}
    assert "ERROR" in severities
    assert {check.check_id for check in report.checks} >= {
        "price_positive",
        "curve_contract_order",
    }


def test_qc_warns_on_zero_volume_and_settle_close_divergence():
    bars = {
        "al": pd.DataFrame(
            [
                {
                    "open": 19000.0,
                    "high": 19100.0,
                    "low": 18900.0,
                    "close": 19000.0,
                    "settle": 19000.0,
                    "volume": 100,
                    "open_interest": 1000,
                    "contract": "al2402",
                },
                {
                    "open": 19010.0,
                    "high": 19110.0,
                    "low": 18910.0,
                    "close": 19020.0,
                    "settle": 19600.0,
                    "volume": 0,
                    "open_interest": 1000,
                    "contract": "al2402",
                },
            ],
            index=[dt.date(2024, 1, 2), dt.date(2024, 1, 3)],
        )
    }

    report = run_panel_qc(snapshot="synthetic", bars=bars, curves={})

    assert report.status == "PASS_WITH_WARNINGS"
    assert {check.severity for check in report.checks} == {"WARN"}
    assert {check.check_id for check in report.checks} >= {
        "volume_nonzero",
        "settle_close_divergence",
    }


def test_qc_treats_price_outliers_as_warnings_and_skips_roll_return():
    bars = {
        "fu": pd.DataFrame(
            [
                {
                    "open": 2300.0,
                    "high": 2310.0,
                    "low": 2290.0,
                    "close": 2300.0,
                    "settle": 2300.0,
                    "volume": 1000,
                    "open_interest": 1000,
                    "contract": "fu2401",
                },
                {
                    "open": 2600.0,
                    "high": 2610.0,
                    "low": 2590.0,
                    "close": 2600.0,
                    "settle": 2600.0,
                    "volume": 1000,
                    "open_interest": 1000,
                    "contract": "fu2405",
                },
                {
                    "open": 2610.0,
                    "high": 2620.0,
                    "low": 2100.0,
                    "close": 2100.0,
                    "settle": 2600.0,
                    "volume": 1000,
                    "open_interest": 1000,
                    "contract": "fu2405",
                },
            ],
            index=[dt.date(2024, 1, 2), dt.date(2024, 1, 3), dt.date(2024, 1, 4)],
        )
    }

    report = run_panel_qc(snapshot="synthetic", bars=bars, curves={})

    assert report.status == "PASS_WITH_WARNINGS"
    assert {check.severity for check in report.checks} == {"WARN"}
    assert {check.check_id for check in report.checks} == {
        "settle_close_divergence",
        "daily_return_threshold",
    }
    assert not any(
        check.check_id == "daily_return_threshold" and check.date == dt.date(2024, 1, 3)
        for check in report.checks
    )
