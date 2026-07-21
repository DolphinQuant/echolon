"""Book backtest models."""
from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .schedule import ExecutionContractSchedule


class BookBacktestConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start: dt.date
    end: dt.date
    initial_equity_rmb: float
    panel_snapshot: str
    panel_manifest_sha256: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    execution_contract_schedule: ExecutionContractSchedule | None = None
    slippage_bps_by_instrument: dict[str, float] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_execution_contract_schedule(self) -> "BookBacktestConfig":
        schedule = self.execution_contract_schedule
        if schedule is None:
            return self
        if self.panel_manifest_sha256 is None:
            raise ValueError(
                "panel_manifest_sha256 is required with an execution contract schedule"
            )
        if self.panel_snapshot != schedule.source_panel_snapshot:
            raise ValueError(
                "execution contract schedule source_panel_snapshot does not match "
                "BookBacktestConfig.panel_snapshot"
            )
        if self.panel_manifest_sha256 != schedule.source_panel_manifest_sha256:
            raise ValueError(
                "execution contract schedule source_panel_manifest_sha256 does not "
                "match BookBacktestConfig.panel_manifest_sha256"
            )
        if self.start < schedule.start or self.end > schedule.end:
            raise ValueError(
                "execution contract schedule does not cover the requested config window"
            )
        return self


class EquityPoint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    date: dt.date
    equity_rmb: float
    cash_rmb: float
    margin_used_rmb: float


class TradeRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    date: dt.date
    instrument: str
    contract: str
    side: str
    lots: float
    intended_price: float
    fill_price: float
    slippage_rmb: float
    commission_rmb: float
    close_today: bool
    realized_pnl_rmb: float
    position_after: float


class Summary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    net_sharpe: float
    ann_return_pct: float
    max_dd_pct: float
    n_trades: int
    fees_total_rmb: float
    slippage_total_rmb: float
    determinism_hash: str


class BookResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    equity_curve: list[EquityPoint]
    trades: list[TradeRecord]
    rebalance_records: list[dict] = Field(default_factory=list)
    daily_returns: list[dict] = Field(default_factory=list)
    events: list[dict] = Field(default_factory=list)
    summary: Summary
