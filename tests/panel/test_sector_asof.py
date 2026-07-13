"""As-of Shenwan sector resolution falsifiers."""
from __future__ import annotations

import datetime as dt

import pandas as pd

from echolon.panel.sector import resolve_sector_asof


def test_reclassified_name_uses_old_sector_before_new_in_date() -> None:
    membership = pd.DataFrame(
        {
            "instrument": ["000001.sz", "000001.sz"],
            "l1_code": ["801010", "801780"],
            "in_date": ["20100101", "20190701"],
            "out_date": ["20190630", None],
        }
    )

    assert (
        resolve_sector_asof(
            membership, "000001.SZ", dt.date(2018, 6, 30)
        )
        == "801010"
    )
    assert (
        resolve_sector_asof(
            membership, "000001.sz", dt.date(2020, 6, 30)
        )
        == "801780"
    )


def test_missing_asof_membership_uses_explicit_fallback_only() -> None:
    membership = pd.DataFrame(
        {
            "instrument": ["000001.sz"],
            "l1_code": ["801780"],
            "in_date": ["20190701"],
            "out_date": [None],
        }
    )

    assert resolve_sector_asof(membership, "000001.sz", "2018-06-30") is None
    assert (
        resolve_sector_asof(
            membership, "000001.sz", "2018-06-30", fallback="UNKNOWN"
        )
        == "UNKNOWN"
    )
