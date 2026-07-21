"""Falsifier: DCE eb/a/b/cs commission == the ratified exchange-standard authority.

Unlike the multiplier/tick specs, these four DCE commissions are pinned to the
exchange-standard per-lot rate (flat 平今) ratified 2026-07-20 — the runtime spec
source must match the authority artifact (instrument-consistency law). akshare's
``futures_fees_info`` carries a systematic +0.01 元/手 broker-negotiated offset that
is deliberately excluded.

Two layers:
  1. an always-on value pin (runs with no external dependency);
  2. a cross-artifact consistency check against the ratified authority JSON in
     ``output_bank`` (skips when the store is unavailable, following the
     ``test_dce_expiry_empirical`` convention).
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from echolon.config.markets.dce.instruments import INSTRUMENTS as DCE

# Exchange-standard per-lot rate (元/手), flat: open = 平昨 = 平今.
RATIFIED = {"eb": 1.00, "a": 2.00, "b": 1.00, "cs": 1.50}


def test_dce_commissions_are_exchange_standard() -> None:
    for code, expected in RATIFIED.items():
        spec = DCE[code]
        assert spec.commission == expected, (code, spec.commission, expected)
        assert spec.commission_type == "per_contract"


def _authority_path() -> Path:
    configured = os.environ.get("DCE_COMMISSION_AUTHORITY_V2")
    if configured:
        return Path(configured)
    return (
        Path(__file__).resolve().parents[4]
        / "output_bank/datasets/dce_commission_authority_v2/artifact.json"
    )


def test_dce_commissions_match_ratified_authority_artifact() -> None:
    """Echolon canonical commission == the v2 authority ``records`` for the 4 products."""
    artifact = _authority_path()
    if not artifact.exists():
        pytest.skip(f"DCE commission authority v2 artifact unavailable: {artifact}")
    records = json.loads(artifact.read_text())["records"]
    for code in RATIFIED:
        assert DCE[code].commission == records[code]["commission"], code
