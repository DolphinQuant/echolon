"""Book backtest models."""
from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, ConfigDict, Field


class BookBacktestConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start: dt.date
    end: dt.date
    initial_equity_rmb: float
    panel_snapshot: str


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
    lots: int
    intended_price: float
    fill_price: float
    slippage_rmb: float
    commission_rmb: float
    close_today: bool
    realized_pnl_rmb: float
    position_after: int


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

