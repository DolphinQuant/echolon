"""Purpose-built daily futures book backtester."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
from dataclasses import dataclass
from decimal import ROUND_CEILING, Decimal
from pathlib import Path
from typing import Any, Mapping, Sequence

import pandas as pd

from echolon.panel import PanelData
from echolon.portfolio import BookState, PortfolioStrategy

from .interface import IBookBacktester
from .models import BookBacktestConfig, BookResult, EquityPoint, Summary, TradeRecord


@dataclass
class _Position:
    lots: float = 0.0
    avg_price: float = 0.0
    contract: str = ""
    opened_date: dt.date | None = None


@dataclass(frozen=True)
class _PendingTarget:
    target_lots: float
    decision_date: dt.date


@dataclass(frozen=True)
class _ExecutionResult:
    cash_delta: float
    deferred: frozenset[str]


@dataclass(frozen=True)
class _RollResult:
    cash_delta: float
    deferred: frozenset[str]


class DailyBookBacktester(IBookBacktester):
    """Daily book simulator with one cash account and futures margin."""

    def __init__(
        self,
        *,
        output_dir: Path,
        slippage_bps: float = 3.0,
        rebalance_weekday: int | None = 4,
        rebalance_interval_weeks: int = 1,
        stamp_duty_schedule: Sequence[tuple[dt.date, float]] | None = None,
    ) -> None:
        self.output_dir = Path(output_dir)
        self.slippage_bps = float(slippage_bps)
        self.rebalance_weekday = rebalance_weekday
        if rebalance_interval_weeks < 1:
            raise ValueError("rebalance_interval_weeks must be >= 1")
        self.rebalance_interval_weeks = int(rebalance_interval_weeks)
        # Optional date-dependent sell-side stamp-duty schedule. ``None`` (the
        # default) keeps the flat per-instrument ``meta.stamp_duty_rate`` and is
        # byte-identical to the historical engine on every path.
        self._stamp_duty_schedule = _normalize_stamp_duty_schedule(stamp_duty_schedule)
        self._last_buy_fill_dates: dict[str, dt.date] = {}

    def _stamp_duty_rate_for(self, trade_date: dt.date) -> float | None:
        """Scheduled sell-side rate for ``trade_date``, or ``None`` when unset.

        ``None`` signals the fee path to keep the flat per-instrument rate, so an
        engine constructed without a schedule behaves exactly as before.
        """
        if self._stamp_duty_schedule is None:
            return None
        return resolve_scheduled_stamp_duty_rate(self._stamp_duty_schedule, trade_date)

    def run(
        self,
        strategy: PortfolioStrategy,
        panel: PanelData,
        config: BookBacktestConfig,
    ) -> BookResult:
        self._last_buy_fill_dates = {}
        dates = [date for date in panel.calendar if config.start <= date <= config.end]
        if len(dates) < 2:
            raise ValueError("book backtest requires at least two panel dates")

        cash = float(config.initial_equity_rmb)
        positions = {instrument: _Position() for instrument in panel.instruments}
        equity_curve: list[EquityPoint] = []
        trades: list[TradeRecord] = []
        rebalance_records: list[dict] = []
        events: list[dict] = []
        pending_targets: dict[str, _PendingTarget] = {}

        for index, date in enumerate(dates):
            view = panel.view(date)
            target_lots = {
                instrument: pending.target_lots
                for instrument, pending in pending_targets.items()
            }
            roll_result = self._roll_changed_main_contracts(
                view,
                positions,
                trades,
                config,
                events,
                target_lots if pending_targets else None,
            )
            cash += roll_result.cash_delta
            if pending_targets:
                execution_result = self._execute_targets(
                    view,
                    positions,
                    target_lots,
                    trades,
                    config,
                    events,
                    blocked_instruments=roll_result.deferred,
                    decision_dates={
                        instrument: pending.decision_date
                        for instrument, pending in pending_targets.items()
                    },
                )
                cash += execution_result.cash_delta
                pending_targets = {
                    instrument: pending
                    for instrument, pending in pending_targets.items()
                    if instrument in execution_result.deferred
                }

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
                for instrument, pending in pending_targets.items():
                    events.append({
                        "date": date.isoformat(),
                        "type": "target_cancelled",
                        "detail": {
                            "instrument": instrument,
                            "target_lots": pending.target_lots,
                            "decision_date": pending.decision_date.isoformat(),
                            "reason": "forced_liquidation",
                        },
                    })
                pending_targets = {}

            equity_curve.append(
                EquityPoint(
                    date=date,
                    equity_rmb=round(equity, 10),
                    cash_rmb=round(cash, 10),
                    margin_used_rmb=round(margin, 10),
                )
            )
            if index < len(dates) - 1 and self._is_rebalance_date(date, dates[0]):
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
                self._merge_pending_targets(
                    pending_targets,
                    target.targets,
                    positions=positions,
                    decision_date=view.date,
                    events=events,
                )
                rebalance_records.append(record.model_dump(mode="json"))

        for instrument, pending in pending_targets.items():
            events.append({
                "date": dates[-1].isoformat(),
                "type": "target_unresolved_at_end",
                "detail": {
                    "instrument": instrument,
                    "target_lots": pending.target_lots,
                    "decision_date": pending.decision_date.isoformat(),
                },
            })

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

    def _is_rebalance_date(self, date: dt.date, start: dt.date) -> bool:
        if self.rebalance_weekday is not None and date.weekday() != self.rebalance_weekday:
            return False
        if self.rebalance_interval_weeks <= 1:
            return True
        weeks_since_start = (date - start).days // 7
        return weeks_since_start % self.rebalance_interval_weeks == 0

    def _execute_targets(
        self,
        view: Any,
        positions: dict[str, _Position],
        targets: Mapping[str, float],
        trades: list[TradeRecord],
        config: BookBacktestConfig,
        events: list[dict],
        *,
        blocked_instruments: frozenset[str] = frozenset(),
        decision_dates: Mapping[str, dt.date] | None = None,
    ) -> _ExecutionResult:
        cash_delta = 0.0
        deferred: set[str] = set()
        for instrument, target in targets.items():
            current = positions[instrument].lots
            diff = float(target) - current
            if abs(diff) <= 1e-12:
                continue
            decision_date = (
                decision_dates[instrument]
                if decision_dates is not None
                else view.date
            )
            if instrument in blocked_instruments:
                deferred.add(instrument)
                events.append({
                    "date": view.date.isoformat(),
                    "type": "target_deferred",
                    "detail": {
                        "instrument": instrument,
                        "target_lots": float(target),
                        "decision_date": decision_date.isoformat(),
                        "reason": "roll_deferred",
                    },
                })
                continue
            bar = view.current_bar(instrument)
            if bar is None:
                deferred.add(instrument)
                events.append({
                    "date": view.date.isoformat(),
                    "type": "target_deferred",
                    "detail": {
                        "instrument": instrument,
                        "target_lots": float(target),
                        "decision_date": decision_date.isoformat(),
                        "reason": "missing_exact_main_bar",
                    },
                })
                continue
            meta = view.meta(instrument)
            intended = _raw_price(bar, "open")
            side = "BUY" if diff > 0 else "SELL"
            if (
                side == "SELL"
                and bool(meta.t_plus_one)
                and self._last_buy_fill_dates.get(instrument) == view.date
            ):
                raise RuntimeError(
                    f"T+1 violation: cannot sell {instrument} shares bought on {view.date}"
                )
            reason = _fill_refusal_reason(bar, side, intended, float(meta.tick))
            if reason is not None:
                deferred.add(instrument)
                events.append({
                    "date": view.date.isoformat(),
                    "type": "fill_refused",
                    "detail": {
                        "instrument": instrument,
                        "side": side,
                        "lots": abs(diff),
                        "target_lots": float(target),
                        "decision_date": decision_date.isoformat(),
                        "reason": reason,
                        "pending_action": "retained",
                    },
                })
                continue
            fill = _slipped_price(
                intended,
                diff,
                self._slippage_bps_for(instrument, config),
                float(meta.tick),
            )
            close_today = _is_close_today(positions[instrument], diff, view.date)
            commission = _commission_rmb(
                meta, fill, abs(diff), close_today=close_today, side=side,
                stamp_duty_rate_override=self._stamp_duty_rate_for(view.date),
            )
            realized = _realized_pnl(positions[instrument], diff, fill, float(meta.multiplier))
            cash_delta += realized - commission
            new_position = _updated_position(positions[instrument], diff, fill, str(bar["contract"]), view.date)
            positions[instrument] = new_position
            if side == "BUY":
                self._last_buy_fill_dates[instrument] = view.date
            trades.append(
                TradeRecord(
                    date=view.date,
                    instrument=instrument,
                    contract=str(bar["contract"]),
                    side=side,
                    lots=abs(diff),
                    intended_price=round(intended, 10),
                    fill_price=round(fill, 10),
                    slippage_rmb=round(abs(fill - intended) * abs(diff) * float(meta.multiplier), 10),
                    commission_rmb=round(commission, 10),
                    close_today=close_today,
                    realized_pnl_rmb=round(realized, 10),
                    position_after=new_position.lots,
                )
            )
        return _ExecutionResult(
            cash_delta=round(cash_delta, 10),
            deferred=frozenset(deferred),
        )

    def _roll_changed_main_contracts(
        self,
        view: Any,
        positions: dict[str, _Position],
        trades: list[TradeRecord],
        config: BookBacktestConfig,
        events: list[dict],
        targets: Mapping[str, float] | None = None,
    ) -> _RollResult:
        """Materialize contract rolls before mark-to-market can drift contracts.

        A position belongs to the contract that opened it. On the first session
        where the main contract changes, close that held contract using its own
        raw contract row, then open the current main contract only for the
        target lot count that should remain after the pending rebalance.
        """
        cash_delta = 0.0
        deferred: set[str] = set()
        for instrument, position in list(positions.items()):
            if position.lots == 0:
                continue
            main_bar = view.current_bar(instrument)
            if main_bar is None:
                deferred.add(instrument)
                events.append({
                    "date": view.date.isoformat(),
                    "type": "roll_deferred",
                    "detail": {
                        "instrument": instrument,
                        "held_contract": position.contract,
                        "reason": "missing_exact_main_bar",
                    },
                })
                continue
            today_contract = str(main_bar["contract"])
            if not position.contract or position.contract == today_contract:
                continue
            meta = view.meta(instrument)
            slippage_bps = self._slippage_bps_for(instrument, config)
            close_bar = view.contract_bar(instrument, position.contract)
            if close_bar is None:
                deferred.add(instrument)
                events.append({
                    "date": view.date.isoformat(),
                    "type": "roll_deferred",
                    "detail": {
                        "instrument": instrument,
                        "held_contract": position.contract,
                        "next_contract": today_contract,
                        "reason": "missing_exact_held_contract_bar",
                    },
                })
                continue
            close_diff = -position.lots
            close_intended = _raw_price(close_bar, "open")
            close_fill = _slipped_price(close_intended, close_diff, slippage_bps, float(meta.tick))
            close_today = _is_close_today(position, close_diff, view.date)
            commission_close = _commission_rmb(meta, close_fill, abs(close_diff), close_today=close_today)
            realized = _realized_pnl(position, close_diff, close_fill, float(meta.multiplier))
            cash_delta += realized - commission_close
            target_lots = float(targets.get(instrument, position.lots)) if targets is not None else position.lots
            positions[instrument] = _Position()
            trades.append(
                TradeRecord(
                    date=view.date,
                    instrument=instrument,
                    contract=position.contract,
                    side="BUY" if close_diff > 0 else "SELL",
                    lots=abs(close_diff),
                    intended_price=round(close_intended, 10),
                    fill_price=round(close_fill, 10),
                    slippage_rmb=round(abs(close_fill - close_intended) * abs(close_diff) * float(meta.multiplier), 10),
                    commission_rmb=round(commission_close, 10),
                    close_today=close_today,
                    realized_pnl_rmb=round(realized, 10),
                    position_after=0,
                )
            )
            if abs(target_lots) <= 1e-12:
                continue
            open_diff = target_lots
            open_intended = _raw_price(main_bar, "open")
            open_fill = _slipped_price(open_intended, open_diff, slippage_bps, float(meta.tick))
            commission_open = _commission_rmb(meta, open_fill, abs(open_diff), close_today=False)
            cash_delta -= commission_open
            positions[instrument] = _Position(
                lots=target_lots,
                avg_price=open_fill,
                contract=today_contract,
                opened_date=view.date,
            )
            trades.append(
                TradeRecord(
                    date=view.date,
                    instrument=instrument,
                    contract=today_contract,
                    side="BUY" if open_diff > 0 else "SELL",
                    lots=abs(open_diff),
                    intended_price=round(open_intended, 10),
                    fill_price=round(open_fill, 10),
                    slippage_rmb=round(abs(open_fill - open_intended) * abs(open_diff) * float(meta.multiplier), 10),
                    commission_rmb=round(commission_open, 10),
                    close_today=False,
                    realized_pnl_rmb=0.0,
                    position_after=target_lots,
                )
            )
        return _RollResult(
            cash_delta=round(cash_delta, 10),
            deferred=frozenset(deferred),
        )

    @staticmethod
    def _merge_pending_targets(
        pending: dict[str, _PendingTarget],
        newest: Mapping[str, float],
        *,
        positions: Mapping[str, _Position],
        decision_date: dt.date,
        events: list[dict],
    ) -> None:
        """Normalize one absolute target book against positions and pending intent.

        Live target books define omitted instruments as zero. A newest explicit
        target replaces prior intent for that name; an omitted flat name cancels
        a deferred opening, while an omitted held name schedules an exit to zero.
        Targets already equal to current lots are pruned.
        """
        normalized: dict[str, float] = {}
        for raw_instrument, target in newest.items():
            instrument = raw_instrument.lower()
            if instrument in normalized:
                raise ValueError(f"duplicate normalized target instrument {instrument}")
            normalized[instrument] = float(target)
        unknown = sorted(set(normalized).difference(positions))
        if unknown:
            raise KeyError(f"targets contain instruments absent from the panel: {unknown}")
        orphaned = sorted(set(pending).difference(positions))
        if orphaned:
            raise KeyError(f"pending targets contain instruments absent from the panel: {orphaned}")

        next_pending: dict[str, _PendingTarget] = {}
        for instrument, position in positions.items():
            is_explicit = instrument in normalized
            target = normalized.get(instrument, 0.0)
            previous = pending.get(instrument)
            if abs(target - position.lots) <= 1e-12:
                if previous is not None:
                    events.append({
                        "date": decision_date.isoformat(),
                        "type": "target_cancelled",
                        "detail": {
                            "instrument": instrument,
                            "target_lots": previous.target_lots,
                            "decision_date": previous.decision_date.isoformat(),
                            "superseding_decision_date": decision_date.isoformat(),
                            "reason": (
                                "superseded_target_already_satisfied"
                                if is_explicit
                                else "omitted_by_new_target_book"
                            ),
                        },
                    })
                continue
            if previous is not None:
                events.append({
                    "date": decision_date.isoformat(),
                    "type": "target_replaced",
                    "detail": {
                        "instrument": instrument,
                        "previous_target_lots": previous.target_lots,
                        "previous_decision_date": previous.decision_date.isoformat(),
                        "new_target_lots": float(target),
                        "new_decision_date": decision_date.isoformat(),
                        "reason": (
                            "explicit_new_target"
                            if is_explicit
                            else "omitted_by_new_target_book"
                        ),
                    },
                })
            next_pending[instrument] = _PendingTarget(
                target_lots=float(target),
                decision_date=decision_date,
            )
        pending.clear()
        pending.update(next_pending)

    def _slippage_bps_for(self, instrument: str, config: BookBacktestConfig) -> float:
        """Return the configured transaction-cost charge for one instrument.

        P5R uses this daily book as the release-candidate evaluator. A single
        book-wide bps value is too easy to undercharge thin contracts, so the
        campaign config may pin conservative per-instrument tiers while older
        callers continue to receive the historical fallback.
        """
        return float(config.slippage_bps_by_instrument.get(instrument, self.slippage_bps))

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


def _slipped_price(price: float, lots: float, slippage_bps: float, tick: float) -> float:
    """Apply slippage in adverse whole ticks, never rounding the charge away."""
    if lots == 0 or slippage_bps <= 0:
        return price
    direction = 1.0 if lots > 0 else -1.0
    if tick <= 0:
        return price * (1.0 + direction * slippage_bps / 10_000.0)
    tick_decimal = Decimal(str(tick))
    offset_ratio = (
        Decimal(str(abs(price)))
        * Decimal(str(slippage_bps))
        / Decimal(10_000)
        / tick_decimal
    )
    offset_ticks = max(1, int(offset_ratio.to_integral_value(rounding=ROUND_CEILING)))
    result = Decimal(str(price)) + Decimal(str(direction)) * offset_ticks * tick_decimal
    return float(result)


def _fill_refusal_reason(bar: Any, side: str, open_raw: float, tick: float) -> str | None:
    """Return an A-share fill-refusal reason, or None when the bar is tradable."""
    if float(bar.get("suspended", 0.0)) == 1.0:
        return "suspended"
    epsilon = tick / 2.0
    limit_up = bar.get("limit_up_price", float("nan"))
    limit_down = bar.get("limit_down_price", float("nan"))
    if side == "BUY" and pd.notna(limit_up) and open_raw >= float(limit_up) - epsilon:
        return "limit_up"
    if side == "SELL" and pd.notna(limit_down) and open_raw <= float(limit_down) + epsilon:
        return "limit_down"
    return None


def _commission_rmb(
    meta: Any,
    price: float,
    lots_abs: float,
    *,
    close_today: bool = False,
    side: str | None = None,
    stamp_duty_rate_override: float | None = None,
) -> float:
    commission = (
        float(meta.close_today_commission)
        if close_today and meta.close_today_commission is not None
        else float(meta.commission)
    )
    notional = price * float(meta.multiplier) * lots_abs
    brokerage = commission * notional if meta.commission_type == "percentage" else commission * lots_abs
    if side is None:
        return brokerage
    if side not in ("BUY", "SELL"):
        raise ValueError("side must be BUY, SELL, or None")
    brokerage = max(brokerage, float(meta.min_commission))
    duty_rate = (
        float(meta.stamp_duty_rate)
        if stamp_duty_rate_override is None
        else float(stamp_duty_rate_override)
    )
    stamp_duty = notional * duty_rate if side == "SELL" else 0.0
    return brokerage + stamp_duty + notional * float(meta.transfer_fee_rate)


def _normalize_stamp_duty_schedule(
    schedule: Sequence[tuple[dt.date, float]] | None,
) -> tuple[tuple[dt.date, float], ...] | None:
    """Validate and freeze an optional (effective_date, sell-side rate) schedule.

    ``None`` is returned unchanged and preserves the flat-rate fee path. A
    provided schedule must be non-empty, carry strictly ascending effective
    dates, and non-negative rates. Malformed cost data is a hard failure, never a
    silent zero.
    """
    if schedule is None:
        return None
    rows = tuple((date, float(rate)) for date, rate in schedule)
    if not rows:
        raise ValueError("stamp_duty_schedule must be non-empty when provided")
    dates = [date for date, _ in rows]
    if any(later <= earlier for earlier, later in zip(dates, dates[1:])):
        raise ValueError("stamp_duty_schedule effective dates must be strictly ascending")
    if any(rate < 0.0 for _, rate in rows):
        raise ValueError("stamp_duty_schedule rates must be non-negative")
    return rows


def resolve_scheduled_stamp_duty_rate(
    schedule: tuple[tuple[dt.date, float], ...], trade_date: dt.date
) -> float:
    """Sell-side stamp-duty rate in force on ``trade_date`` (boundary-INCLUSIVE).

    The rate is the one carried by the latest effective date at or before the
    trade date, so a trade ON an effective date already pays the NEW rate. This
    matches China's 2023-08-28 halving, announced "自2023年8月28日起" (in effect
    from that date on): a sale on 2023-08-28 pays the reduced rate. A trade before
    the first effective date is a schedule-coverage failure, not a silent zero.
    """
    resolved: float | None = None
    for effective_date, rate in schedule:
        if effective_date <= trade_date:
            resolved = rate
        else:
            break
    if resolved is None:
        raise ValueError(
            f"stamp_duty_schedule does not cover trade date {trade_date.isoformat()}"
        )
    return resolved


def _updated_position(position: _Position, diff: float, fill: float, contract: str, date: dt.date) -> _Position:
    target = position.lots + diff
    if abs(target) <= 1e-12:
        return _Position()
    if position.lots == 0 or (position.lots > 0) != (target > 0):
        return _Position(lots=target, avg_price=fill, contract=contract, opened_date=date)
    if abs(target) > abs(position.lots):
        old_abs = abs(position.lots)
        diff_abs = abs(diff)
        avg = (position.avg_price * old_abs + fill * diff_abs) / (old_abs + diff_abs)
        return _Position(lots=target, avg_price=avg, contract=contract, opened_date=position.opened_date)
    return _Position(lots=target, avg_price=position.avg_price, contract=position.contract, opened_date=position.opened_date)


def _realized_pnl(position: _Position, diff: float, fill: float, multiplier: float) -> float:
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
        bar = _valuation_bar(view, instrument, position.contract)
        meta = view.meta(instrument)
        total += abs(position.lots) * _raw_price(bar, "settle") * float(meta.multiplier) * float(meta.margin_rate)
    return round(total, 10)


def _unrealized_pnl(view: Any, positions: Mapping[str, _Position]) -> float:
    total = 0.0
    for instrument, position in positions.items():
        if position.lots == 0:
            continue
        bar = _valuation_bar(view, instrument, position.contract)
        meta = view.meta(instrument)
        total += position.lots * (_raw_price(bar, "settle") - position.avg_price) * float(meta.multiplier)
    return round(total, 10)


def _valuation_bar(view: Any, instrument: str, contract: str) -> Any:
    """Return the held contract's latest as-of row; never use for execution.

    Valuation may carry one contract's own settlement across its closed session.
    It must never substitute a different main contract, which would manufacture
    PnL while an executable roll is deferred.
    """
    if not contract:
        raise ValueError(f"held position for {instrument} has no contract identity")
    if not hasattr(view, "contract_bar"):
        raise TypeError("book view must implement contract_bar for position valuation")
    exact = view.contract_bar(instrument, contract)
    if exact is not None:
        return exact
    if not hasattr(view, "contract_bar_asof"):
        raise TypeError("book view must implement contract_bar_asof for position valuation")
    row = view.contract_bar_asof(instrument, contract)
    if row is None:
        raise ValueError(
            f"no as-of valuation row for held contract {contract} ({instrument}) "
            f"on {view.date.isoformat()}"
        )
    return row


def _raw_price(row: Any, column: str) -> float:
    raw_column = f"{column}_raw"
    if raw_column in row:
        return float(row[raw_column])
    return float(row[column])


def _is_close_today(position: _Position, diff: float, date: dt.date) -> bool:
    if position.lots == 0 or (position.lots > 0) == (diff > 0):
        return False
    return position.opened_date == date


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
