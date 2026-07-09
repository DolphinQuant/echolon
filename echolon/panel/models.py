"""Pydantic models for panel snapshots."""
from __future__ import annotations

import datetime as dt
import warnings
from typing import Literal

from pydantic import BaseModel, Field

warnings.filterwarnings(
    "ignore",
    message='Field name "schema" in .* shadows an attribute in parent "BaseModel"',
    category=UserWarning,
    module=__name__,
)


class CurvePoint(BaseModel):
    near_contract: str
    near_settle: float
    far_contract: str
    far_settle: float
    days_between: int


class InstrumentMeta(BaseModel):
    instrument_id: str
    sector: str
    multiplier: float
    tick: float
    margin_rate: float
    commission: float
    commission_type: str
    close_today_commission: float | None = None
    currency: Literal["RMB"] = "RMB"


class PanelManifest(BaseModel):
    schema: Literal["panel/v1"] = "panel/v1"
    version: str
    created_at: str
    source_refs: list[str]
    calendar_start: dt.date
    calendar_end: dt.date
    instruments: list[str]
    files: dict[str, str] = Field(default_factory=dict)
    qc_report: str
    qc_status: Literal["PASS", "PASS_WITH_WARNINGS"]


class QCCheck(BaseModel):
    check_id: str
    instrument: str | None = None
    date: dt.date | None = None
    severity: Literal["ERROR", "WARN"]
    message: str
    value: float | None = None


class QCReport(BaseModel):
    schema: Literal["qc/v1"] = "qc/v1"
    snapshot: str
    status: Literal["PASS", "PASS_WITH_WARNINGS", "FAIL"]
    checks: list[QCCheck] = Field(default_factory=list)
