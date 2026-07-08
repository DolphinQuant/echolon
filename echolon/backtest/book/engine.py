"""Purpose-built daily futures book backtester."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

from echolon.panel import PanelData
from echolon.portfolio import BookState, PortfolioStrategy

from .interface import IBookBacktester
from .models import BookBacktestConfig, BookResult, EquityPoint, Summary, TradeRecord


@dataclass
class _Position:
    lots: int = 0
    avg_price: float = 0.0
    contract: str = ""


class DailyBookBacktester(IBookBacktester):
    """Daily book simulator with one cash account and futures margin."""

    def __init__(self, *, output_dir: Path, slippage_bps: float = 3.0) -> None:
        self.output_dir = Path(output_dir)
        self.slippage_bps = float(slippage_bps)

    def run(
        self,
        strategy: PortfolioStrategy,
        panel: PanelData,
        config: BookBacktestConfig,
    ) -> BookResult:
        dates = [date for date in panel.calendar if config.start <= date <= config.end]
        if len(dates) < 2:
            raise ValueError("book backtest requires at least two panel dates")

        cash = float(config.initial_equity_rmb)
        positions = {instrument: _Position() for instrument in panel.instruments}
        equity_curve: list[EquityPoint] = []
        trades: list[TradeRecord] = []
        rebalance_records: list[dict] = []
        events: list[dict] = []
        pending_targets: dict[str, int] | None = None

        for index, date in enumerate(dates):
            view = panel.view(date)
            if pending_targets is not None:
                cash += self._execute_targets(view, positions, pending_targets, trades)
                pending_targets = None

            margin = _margin_used(view, positions)
            equity = cash + _unrealized_pnl(view, positions)
            if margin > equity:
                events.append({
                    "date": date.isoformat(),
                    "type": "forced_liquidation",
                    "detail": {"margin_used_rmb": round(margin, 10), "equity_rmb": round(equity, 10)},
                })
                cash = equity
                positions = {instrument: _Position() for instrument in panel.instruments}
                margin = 0.0

            equity_curve.append(
                EquityPoint(
                    date=date,
                    equity_rmb=round(equity, 10),
                    cash_rmb=round(cash, 10),
                    margin_used_rmb=round(margin, 10),
                )
            )
            if index < len(dates) - 1:
                book = BookState(
                    date=date,
                    equity_rmb=equity,
                    cash_rmb=cash,
                    margin_used_rmb=margin,
                    positions={
                        instrument: {
                            "lots": position.lots,
                            "avg_price": position.avg_price,
                            "contract": position.contract,
                            "margin_rmb": 0.0,
                        }
                        for instrument, position in positions.items()
                        if position.lots
                    },
                )
                target, record = strategy.rebalance(view, book)
                pending_targets = dict(target.targets)
                rebalance_records.append(record.model_dump(mode="json"))

        daily_returns = _daily_returns(equity_curve)
        summary = _summary(equity_curve, trades, daily_returns)
        result = BookResult(
            equity_curve=equity_curve,
            trades=trades,
            rebalance_records=rebalance_records,
            daily_returns=daily_returns,
            events=events,
            summary=summary,
        )
        self._write_outputs(result)
        return result

    def _execute_targets(
        self,
        view: Any,
        positions: dict[str, _Position],
        targets: Mapping[str, int],
        trades: list[TradeRecord],
    ) -> float:
        cash_delta = 0.0
        for instrument, target in targets.items():
            current = positions[instrument].lots
            diff = int(target) - current
            if diff == 0:
                continue
            bar = view.bars(instrument, 1).iloc[-1]
            meta = view.meta(instrument)
            intended = float(bar["open"])
            fill = _slipped_price(intended, diff, self.slippage_bps, float(meta.tick))
            commission = _commission_rmb(meta, fill, abs(diff))
            realized = _realized_pnl(positions[instrument], diff, fill, float(meta.multiplier))
            cash_delta += realized - commission
            new_position = _updated_position(positions[instrument], diff, fill, str(bar["contract"]))
            positions[instrument] = new_position
            trades.append(
                TradeRecord(
                    date=view.date,
                    instrument=instrument,
                    contract=str(bar["contract"]),
                    side="BUY" if diff > 0 else "SELL",
                    lots=abs(diff),
                    intended_price=round(intended, 10),
                    fill_price=round(fill, 10),
                    slippage_rmb=round(abs(fill - intended) * abs(diff) * float(meta.multiplier), 10),
                    commission_rmb=round(commission, 10),
                    close_today=False,
                    realized_pnl_rmb=round(realized, 10),
                    position_after=new_position.lots,
                )
            )
        return round(cash_delta, 10)

    def _write_outputs(self, result: BookResult) -> None:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        pd.DataFrame([row.model_dump(mode="json") for row in result.equity_curve]).to_csv(
            self.output_dir / "equity_curve.csv",
            index=False,
        )
        pd.DataFrame([row.model_dump(mode="json") for row in result.trades]).to_csv(
            self.output_dir / "trades.csv",
            index=False,
        )
        pd.DataFrame(result.daily_returns).to_csv(self.output_dir / "daily_returns.csv", index=False)
        _write_jsonl(self.output_dir / "rebalance_records.jsonl", result.rebalance_records)
        _write_jsonl(self.output_dir / "events.jsonl", result.events)
        (self.output_dir / "summary.json").write_text(
            json.dumps(result.summary.model_dump(mode="json"), sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )


def _slipped_price(price: float, lots: int, slippage_bps: float, tick: float) -> float:
    direction = 1.0 if lots > 0 else -1.0
    raw = price * (1.0 + direction * slippage_bps / 10_000.0)
    return round(raw / tick) * tick if tick > 0 else raw


def _commission_rmb(meta: Any, price: float, lots_abs: int) -> float:
    if meta.commission_type == "percentage":
        return float(meta.commission) * price * float(meta.multiplier) * lots_abs
    return float(meta.commission) * lots_abs


def _updated_position(position: _Position, diff: int, fill: float, contract: str) -> _Position:
    target = position.lots + diff
    if target == 0:
        return _Position()
    if position.lots == 0 or (position.lots > 0) != (target > 0):
        return _Position(lots=target, avg_price=fill, contract=contract)
    if abs(target) > abs(position.lots):
        old_abs = abs(position.lots)
        diff_abs = abs(diff)
        avg = (position.avg_price * old_abs + fill * diff_abs) / (old_abs + diff_abs)
        return _Position(lots=target, avg_price=avg, contract=contract)
    return _Position(lots=target, avg_price=position.avg_price, contract=position.contract)


def _realized_pnl(position: _Position, diff: int, fill: float, multiplier: float) -> float:
    if position.lots == 0 or (position.lots > 0) == (diff > 0):
        return 0.0
    closing_lots = min(abs(position.lots), abs(diff))
    direction = 1.0 if position.lots > 0 else -1.0
    return closing_lots * (fill - position.avg_price) * multiplier * direction


def _margin_used(view: Any, positions: Mapping[str, _Position]) -> float:
    total = 0.0
    for instrument, position in positions.items():
        if position.lots == 0:
            continue
        bar = view.bars(instrument, 1).iloc[-1]
        meta = view.meta(instrument)
        total += abs(position.lots) * float(bar["settle"]) * float(meta.multiplier) * float(meta.margin_rate)
    return round(total, 10)


def _unrealized_pnl(view: Any, positions: Mapping[str, _Position]) -> float:
    total = 0.0
    for instrument, position in positions.items():
        if position.lots == 0:
            continue
        bar = view.bars(instrument, 1).iloc[-1]
        meta = view.meta(instrument)
        total += position.lots * (float(bar["settle"]) - position.avg_price) * float(meta.multiplier)
    return round(total, 10)


def _daily_returns(equity_curve: list[EquityPoint]) -> list[dict]:
    rows: list[dict] = []
    for previous, current in zip(equity_curve, equity_curve[1:]):
        ret = current.equity_rmb / previous.equity_rmb - 1.0 if previous.equity_rmb else 0.0
        rows.append({"date": current.date.isoformat(), "ret": round(ret, 16)})
    return rows


def _summary(
    equity_curve: list[EquityPoint],
    trades: list[TradeRecord],
    daily_returns: list[dict],
) -> Summary:
    returns = [row["ret"] for row in daily_returns]
    mean = sum(returns) / len(returns) if returns else 0.0
    variance = sum((value - mean) ** 2 for value in returns) / (len(returns) - 1) if len(returns) > 1 else 0.0
    sharpe = mean / math.sqrt(variance) * math.sqrt(252.0) if variance > 0 else 0.0
    start = equity_curve[0].equity_rmb
    end = equity_curve[-1].equity_rmb
    ann_return = (end / start - 1.0) * 100.0 if start else 0.0
    peak = -math.inf
    max_dd = 0.0
    for row in equity_curve:
        peak = max(peak, row.equity_rmb)
        if peak > 0:
            max_dd = max(max_dd, (peak - row.equity_rmb) / peak * 100.0)
    fees = sum(trade.commission_rmb for trade in trades)
    slippage = sum(trade.slippage_rmb for trade in trades)
    base_payload = {
        "equity_curve": [row.model_dump(mode="json") for row in equity_curve],
        "trades": [row.model_dump(mode="json") for row in trades],
        "daily_returns": daily_returns,
    }
    digest = hashlib.sha256(
        json.dumps(base_payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return Summary(
        net_sharpe=round(sharpe, 12),
        ann_return_pct=round(ann_return, 12),
        max_dd_pct=round(max_dd, 12),
        n_trades=len(trades),
        fees_total_rmb=round(fees, 10),
        slippage_total_rmb=round(slippage, 10),
        determinism_hash=digest,
    )


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
