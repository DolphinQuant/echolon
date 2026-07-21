"""Purpose-built daily futures book backtester."""
from __future__ import annotations

import bisect
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
from .nominal_schedule import (
    SCHEDULED,
    NominalCycleSchedule,
    NominalCycleScheduleRow,
)
from .schedule import (
    EXECUTABLE_STATUS,
    ExecutionContractSchedule,
    ExecutionContractScheduleRow,
)


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
    eligible_fill_date: dt.date | None = None
    nominal_cycle_schedule_sha256: str | None = None
    cycle_id: str | None = None
    nominal_date: dt.date | None = None


@dataclass(frozen=True)
class _ExecutionResult:
    cash_delta: float
    deferred: frozenset[str]


@dataclass(frozen=True)
class _RollResult:
    cash_delta: float
    deferred: frozenset[str]


@dataclass(frozen=True)
class _ExecutionContractBinding:
    schedule: ExecutionContractSchedule
    rows: Mapping[tuple[dt.date, str], ExecutionContractScheduleRow]


@dataclass(frozen=True)
class _NominalCycleBinding:
    schedule: NominalCycleSchedule
    decisions: Mapping[dt.date, NominalCycleScheduleRow]
    skipped_events_by_emit_date: Mapping[dt.date, tuple[dict, ...]]


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
        execution_contract_binding = _bind_execution_contract_schedule(
            panel, config, dates
        )
        nominal_cycle_binding = _bind_nominal_cycle_schedule(panel, config, dates)

        cash = float(config.initial_equity_rmb)
        positions = {instrument: _Position() for instrument in panel.instruments}
        equity_curve: list[EquityPoint] = []
        trades: list[TradeRecord] = []
        rebalance_records: list[dict] = []
        events: list[dict] = []
        pending_targets: dict[str, _PendingTarget] = {}
        if execution_contract_binding is not None:
            events.append(
                _execution_contract_schedule_bound_event(
                    execution_contract_binding.schedule,
                    config,
                    dates[0],
                )
            )
        if nominal_cycle_binding is not None:
            events.append(
                _nominal_cycle_schedule_bound_event(
                    nominal_cycle_binding.schedule,
                    config,
                    dates[0],
                )
            )

        for index, date in enumerate(dates):
            if nominal_cycle_binding is not None:
                events.extend(
                    nominal_cycle_binding.skipped_events_by_emit_date.get(date, ())
                )
            view = panel.view(date)
            eligible_pending = {
                instrument: pending
                for instrument, pending in pending_targets.items()
                if pending.eligible_fill_date is None
                or date >= pending.eligible_fill_date
            }
            target_lots = {
                instrument: pending.target_lots
                for instrument, pending in eligible_pending.items()
            }
            roll_result = self._roll_changed_main_contracts(
                view,
                positions,
                trades,
                config,
                events,
                target_lots if eligible_pending else None,
                pending_metadata=eligible_pending,
                execution_contract_rows=(
                    execution_contract_binding.rows
                    if execution_contract_binding is not None
                    else None
                ),
            )
            cash += roll_result.cash_delta
            if eligible_pending:
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
                        for instrument, pending in eligible_pending.items()
                    },
                    pending_metadata=eligible_pending,
                    execution_contract_rows=(
                        execution_contract_binding.rows
                        if execution_contract_binding is not None
                        else None
                    ),
                )
                cash += execution_result.cash_delta
                eligible_instruments = set(eligible_pending)
                pending_targets = {
                    instrument: pending
                    for instrument, pending in pending_targets.items()
                    if instrument not in eligible_instruments
                    or instrument in execution_result.deferred
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
                            **_pending_cycle_detail(pending),
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
            nominal_cycle_row = (
                nominal_cycle_binding.decisions.get(date)
                if nominal_cycle_binding is not None
                else None
            )
            if nominal_cycle_binding is not None:
                is_rebalance = nominal_cycle_row is not None
            else:
                is_rebalance = index < len(dates) - 1 and self._is_rebalance_date(
                    date, dates[0]
                )
            if is_rebalance:
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
                if execution_contract_binding is not None:
                    _validate_target_schedule_scope(
                        target.targets,
                        execution_contract_binding.schedule.instruments,
                    )
                self._merge_pending_targets(
                    pending_targets,
                    target.targets,
                    positions=positions,
                    decision_date=view.date,
                    events=events,
                    nominal_cycle_row=nominal_cycle_row,
                    nominal_cycle_schedule_sha256=(
                        nominal_cycle_binding.schedule.sha256
                        if nominal_cycle_binding is not None
                        else None
                    ),
                )
                record_payload = record.model_dump(mode="json")
                if nominal_cycle_binding is not None:
                    assert nominal_cycle_row is not None
                    record_payload["nominal_cycle_schedule"] = (
                        _nominal_cycle_provenance(
                            nominal_cycle_binding.schedule.sha256,
                            nominal_cycle_row,
                        )
                    )
                rebalance_records.append(record_payload)

        for instrument, pending in pending_targets.items():
            events.append({
                "date": dates[-1].isoformat(),
                "type": "target_unresolved_at_end",
                "detail": {
                    "instrument": instrument,
                    "target_lots": pending.target_lots,
                    "decision_date": pending.decision_date.isoformat(),
                    **_pending_cycle_detail(pending),
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
        pending_metadata: Mapping[str, _PendingTarget] | None = None,
        execution_contract_rows: Mapping[
            tuple[dt.date, str], ExecutionContractScheduleRow
        ]
        | None = None,
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
            cycle_detail = (
                _pending_cycle_detail(pending_metadata[instrument])
                if pending_metadata is not None and instrument in pending_metadata
                else {}
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
                        **cycle_detail,
                    },
                })
                continue
            if execution_contract_rows is None:
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
                            **cycle_detail,
                        },
                    })
                    continue
            else:
                schedule_row = _required_execution_contract_row(
                    execution_contract_rows, view.date, instrument
                )
                if schedule_row.status != EXECUTABLE_STATUS:
                    deferred.add(instrument)
                    events.append({
                        "date": view.date.isoformat(),
                        "type": "target_deferred",
                        "detail": {
                            "instrument": instrument,
                            "target_lots": float(target),
                            "decision_date": decision_date.isoformat(),
                            "reason": "scheduled_contract_non_executable",
                            "schedule_status": schedule_row.status,
                            "scheduled_contract": schedule_row.contract,
                            "source_date": (
                                schedule_row.source_date.isoformat()
                                if schedule_row.source_date is not None
                                else None
                            ),
                            **cycle_detail,
                        },
                    })
                    continue
                assert schedule_row.contract is not None
                bar = view.contract_bar(instrument, schedule_row.contract)
                if bar is None:
                    deferred.add(instrument)
                    events.append({
                        "date": view.date.isoformat(),
                        "type": "target_deferred",
                        "detail": {
                            "instrument": instrument,
                            "target_lots": float(target),
                            "decision_date": decision_date.isoformat(),
                            "reason": "missing_exact_scheduled_contract_bar",
                            "scheduled_contract": schedule_row.contract,
                            "source_date": schedule_row.source_date.isoformat(),
                            **cycle_detail,
                        },
                    })
                    continue
                _validate_returned_contract_bar(
                    bar, instrument, schedule_row.contract, view.date
                )
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
                        **cycle_detail,
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
        *,
        pending_metadata: Mapping[str, _PendingTarget] | None = None,
        execution_contract_rows: Mapping[
            tuple[dt.date, str], ExecutionContractScheduleRow
        ]
        | None = None,
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
            cycle_detail = (
                _pending_cycle_detail(pending_metadata[instrument])
                if pending_metadata is not None and instrument in pending_metadata
                else {}
            )
            if execution_contract_rows is None:
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
                            **cycle_detail,
                        },
                    })
                    continue
                today_contract = str(main_bar["contract"])
            else:
                schedule_row = _required_execution_contract_row(
                    execution_contract_rows, view.date, instrument
                )
                if schedule_row.status != EXECUTABLE_STATUS:
                    deferred.add(instrument)
                    events.append({
                        "date": view.date.isoformat(),
                        "type": "roll_deferred",
                        "detail": {
                            "instrument": instrument,
                            "held_contract": position.contract,
                            "reason": "scheduled_contract_non_executable",
                            "schedule_status": schedule_row.status,
                            "scheduled_contract": schedule_row.contract,
                            "source_date": (
                                schedule_row.source_date.isoformat()
                                if schedule_row.source_date is not None
                                else None
                            ),
                            **cycle_detail,
                        },
                    })
                    continue
                assert schedule_row.contract is not None
                today_contract = schedule_row.contract
                if not position.contract:
                    raise ValueError(
                        f"held position for {instrument} has no contract identity"
                    )
                if position.contract == today_contract:
                    continue
                main_bar = view.contract_bar(instrument, today_contract)
                if main_bar is None:
                    deferred.add(instrument)
                    events.append({
                        "date": view.date.isoformat(),
                        "type": "roll_deferred",
                        "detail": {
                            "instrument": instrument,
                            "held_contract": position.contract,
                            "next_contract": today_contract,
                            "reason": "missing_exact_scheduled_contract_bar",
                            "source_date": schedule_row.source_date.isoformat(),
                            **cycle_detail,
                        },
                    })
                    continue
                _validate_returned_contract_bar(
                    main_bar, instrument, today_contract, view.date
                )
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
                        **cycle_detail,
                    },
                })
                continue
            if execution_contract_rows is not None:
                _validate_returned_contract_bar(
                    close_bar, instrument, position.contract, view.date
                )
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
        nominal_cycle_row: NominalCycleScheduleRow | None = None,
        nominal_cycle_schedule_sha256: str | None = None,
    ) -> None:
        """Normalize one absolute target book against positions and pending intent.

        Live target books define omitted instruments as zero. A newest explicit
        target replaces prior intent for that name; an omitted flat name cancels
        a deferred opening, while an omitted held name schedules an exit to zero.
        Targets already equal to current lots are pruned.
        """
        if (nominal_cycle_row is None) != (nominal_cycle_schedule_sha256 is None):
            raise ValueError(
                "nominal cycle row and schedule hash must be supplied together"
            )
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
                            **_pending_cycle_detail(previous),
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
                        **_pending_cycle_detail(previous, prefix="previous_"),
                        **(
                            _nominal_cycle_pending_fields(
                                nominal_cycle_schedule_sha256,
                                nominal_cycle_row,
                                prefix="new_",
                            )
                            if nominal_cycle_row is not None
                            and nominal_cycle_schedule_sha256 is not None
                            else {}
                        ),
                    },
                })
            next_pending[instrument] = _PendingTarget(
                target_lots=float(target),
                decision_date=decision_date,
                eligible_fill_date=(
                    nominal_cycle_row.fill_date
                    if nominal_cycle_row is not None
                    else None
                ),
                nominal_cycle_schedule_sha256=nominal_cycle_schedule_sha256,
                cycle_id=(
                    nominal_cycle_row.cycle_id
                    if nominal_cycle_row is not None
                    else None
                ),
                nominal_date=(
                    nominal_cycle_row.nominal_date
                    if nominal_cycle_row is not None
                    else None
                ),
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


def _nominal_cycle_pending_fields(
    schedule_sha256: str,
    row: NominalCycleScheduleRow,
    *,
    prefix: str = "",
) -> dict[str, str]:
    assert row.decision_date is not None
    assert row.fill_date is not None
    return {
        f"{prefix}nominal_cycle_schedule_sha256": schedule_sha256,
        f"{prefix}cycle_id": row.cycle_id,
        f"{prefix}nominal_date": row.nominal_date.isoformat(),
        f"{prefix}eligible_fill_date": row.fill_date.isoformat(),
    }


def _pending_cycle_detail(
    pending: _PendingTarget,
    *,
    prefix: str = "",
) -> dict[str, str]:
    if pending.cycle_id is None:
        return {}
    if (
        pending.nominal_cycle_schedule_sha256 is None
        or pending.nominal_date is None
        or pending.eligible_fill_date is None
    ):
        raise ValueError("pending nominal-cycle provenance is incomplete")
    return {
        f"{prefix}nominal_cycle_schedule_sha256": (
            pending.nominal_cycle_schedule_sha256
        ),
        f"{prefix}cycle_id": pending.cycle_id,
        f"{prefix}nominal_date": pending.nominal_date.isoformat(),
        f"{prefix}eligible_fill_date": pending.eligible_fill_date.isoformat(),
    }


def _nominal_cycle_provenance(
    schedule_sha256: str,
    row: NominalCycleScheduleRow,
) -> dict[str, str | None]:
    return {
        "sha256": schedule_sha256,
        "cycle_id": row.cycle_id,
        "nominal_date": row.nominal_date.isoformat(),
        "decision_date": (
            row.decision_date.isoformat() if row.decision_date is not None else None
        ),
        "fill_date": row.fill_date.isoformat() if row.fill_date is not None else None,
        "exit_fill_date": (
            row.exit_fill_date.isoformat()
            if row.exit_fill_date is not None
            else None
        ),
    }


def _bind_nominal_cycle_schedule(
    panel: PanelData,
    config: BookBacktestConfig,
    dates: Sequence[dt.date],
) -> _NominalCycleBinding | None:
    """Revalidate a strict schedule and bind it to the full panel calendar."""
    configured = config.nominal_cycle_schedule
    if config.rebalance_mode == "legacy":
        if configured is not None:
            raise ValueError("legacy rebalance mode cannot bind a nominal-cycle schedule")
        return None
    if configured is None:
        raise ValueError("nominal-cycle rebalance mode requires a schedule")

    schedule = NominalCycleSchedule.model_validate(
        configured.model_dump(mode="python")
    )
    if config.panel_manifest_sha256 is None:
        raise ValueError("panel_manifest_sha256 is required with a nominal-cycle schedule")
    if config.panel_snapshot != schedule.source_panel_snapshot:
        raise ValueError("nominal-cycle schedule snapshot does not match config")
    if config.panel_manifest_sha256 != schedule.source_panel_manifest_sha256:
        raise ValueError("nominal-cycle schedule manifest hash does not match config")

    panel_calendar = tuple(panel.calendar)
    if (
        any(not isinstance(date, dt.date) for date in panel_calendar)
        or tuple(sorted(set(panel_calendar))) != panel_calendar
    ):
        raise ValueError(
            "book panel calendar must contain unique, strictly increasing dates"
        )
    if panel_calendar != schedule.panel_union_sessions:
        raise ValueError(
            "nominal-cycle schedule embedded panel union sessions do not match "
            "the full panel calendar"
        )
    expected_run_dates = tuple(
        date for date in panel_calendar if config.start <= date <= config.end
    )
    if tuple(dates) != expected_run_dates:
        raise ValueError("book run dates are inconsistent with the panel union calendar")
    if dates[0] != config.start or dates[-1] != config.end:
        raise ValueError(
            "strict nominal-cycle run bounds must be exact panel union sessions; "
            f"requested={config.start.isoformat()}..{config.end.isoformat()}, "
            f"resolved={dates[0].isoformat()}..{dates[-1].isoformat()}"
        )

    panel_snapshot = getattr(panel, "snapshot_version", None)
    if panel_snapshot != schedule.source_panel_snapshot:
        raise ValueError(
            "book panel snapshot does not match the nominal-cycle schedule: "
            f"panel={panel_snapshot!r}, schedule={schedule.source_panel_snapshot!r}"
        )
    panel_manifest = getattr(panel, "manifest", None)
    if (
        panel_manifest is not None
        and getattr(panel_manifest, "version", None) != panel_snapshot
    ):
        raise ValueError("book panel manifest version and snapshot_version are inconsistent")
    exposed_manifest_sha = getattr(panel, "manifest_sha256", None)
    if (
        exposed_manifest_sha is not None
        and exposed_manifest_sha != schedule.source_panel_manifest_sha256
    ):
        raise ValueError("book panel exposed manifest hash does not match nominal schedule")
    snapshot_dir = getattr(panel, "snapshot_dir", None)
    if snapshot_dir is not None:
        manifest_path = Path(snapshot_dir) / "manifest.json"
        if not manifest_path.is_file():
            raise ValueError(
                f"book panel snapshot is missing manifest.json: {manifest_path}"
            )
        actual_manifest_sha256 = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
        if actual_manifest_sha256 != schedule.source_panel_manifest_sha256:
            raise ValueError(
                "book panel manifest bytes do not match the nominal-cycle schedule: "
                f"expected {schedule.source_panel_manifest_sha256}, "
                f"got {actual_manifest_sha256}"
            )

    required_nominal_start = max(
        schedule.nominal_anchor,
        _nominal_grid_floor(
            schedule.nominal_anchor, config.start, schedule.interval_calendar_days
        ),
    )
    required_nominal_end = max(
        schedule.nominal_anchor,
        _nominal_grid_floor(
            schedule.nominal_anchor, config.end, schedule.interval_calendar_days
        ),
    )
    if (
        schedule.nominal_start > required_nominal_start
        or schedule.nominal_end < required_nominal_end
    ):
        raise ValueError(
            "nominal-cycle schedule does not cover the run's anchor-aligned "
            "nominal cycles"
        )

    decisions: dict[dt.date, NominalCycleScheduleRow] = {}
    skipped_events: list[dict] = []
    for row in schedule.rows:
        relevant_date = row.decision_date or row.nominal_date
        if not (config.start <= relevant_date <= config.end):
            continue
        if row.decision_status != SCHEDULED:
            skipped_events.append(
                _nominal_cycle_skipped_event(schedule.sha256, row, row.decision_status)
            )
            continue
        if row.fill_status != SCHEDULED:
            skipped_events.append(
                _nominal_cycle_skipped_event(schedule.sha256, row, row.fill_status)
            )
            continue
        assert row.decision_date is not None
        assert row.fill_date is not None
        if row.fill_date > config.end:
            skipped_events.append(
                _nominal_cycle_skipped_event(
                    schedule.sha256, row, "fill_outside_run_window"
                )
            )
            continue
        if row.decision_date in decisions:
            raise ValueError(
                "multiple nominal cycles resolve to the same scheduled decision date: "
                f"{row.decision_date.isoformat()}"
            )
        decisions[row.decision_date] = row

    skipped_by_emit_date: dict[dt.date, list[dict]] = {}
    for event in skipped_events:
        semantic_date = dt.date.fromisoformat(event["date"])
        emit_index = bisect.bisect_left(dates, semantic_date)
        if emit_index >= len(dates):
            raise ValueError("nominal-cycle skip has no in-window emission date")
        skipped_by_emit_date.setdefault(dates[emit_index], []).append(event)

    return _NominalCycleBinding(
        schedule=schedule,
        decisions=decisions,
        skipped_events_by_emit_date={
            date: tuple(items) for date, items in skipped_by_emit_date.items()
        },
    )


def _nominal_grid_floor(
    anchor: dt.date,
    date: dt.date,
    interval_calendar_days: int,
) -> dt.date:
    intervals = (date - anchor).days // interval_calendar_days
    return anchor + dt.timedelta(days=intervals * interval_calendar_days)


def _nominal_cycle_schedule_bound_event(
    schedule: NominalCycleSchedule,
    config: BookBacktestConfig,
    first_panel_date: dt.date,
) -> dict:
    return {
        "date": first_panel_date.isoformat(),
        "type": "nominal_cycle_schedule_bound",
        "detail": {
            "sha256": schedule.sha256,
            "source_panel_snapshot": schedule.source_panel_snapshot,
            "source_panel_manifest_sha256": schedule.source_panel_manifest_sha256,
            "authoritative_calendar_id": schedule.authoritative_calendar_id,
            "authoritative_calendar_source_sha256": (
                schedule.authoritative_calendar_source_sha256
            ),
            "authoritative_coverage_basis": schedule.authoritative_coverage_basis,
            "authoritative_sessions_sha256": schedule.authoritative_sessions_sha256,
            "panel_union_sessions_sha256": schedule.panel_union_sessions_sha256,
            "cadence_id": schedule.cadence_id,
            "nominal_anchor": schedule.nominal_anchor.isoformat(),
            "nominal_window": {
                "start": schedule.nominal_start.isoformat(),
                "end": schedule.nominal_end.isoformat(),
            },
            "run_window": {
                "start": config.start.isoformat(),
                "end": config.end.isoformat(),
            },
        },
    }


def _nominal_cycle_skipped_event(
    schedule_sha256: str,
    row: NominalCycleScheduleRow,
    reason: str,
) -> dict:
    event_date = row.decision_date or row.nominal_date
    return {
        "date": event_date.isoformat(),
        "type": "nominal_cycle_skipped",
        "detail": {
            **_nominal_cycle_provenance(schedule_sha256, row),
            "decision_status": row.decision_status,
            "fill_status": row.fill_status,
            "exit_fill_status": row.exit_fill_status,
            "reason": reason,
        },
    }


def _bind_execution_contract_schedule(
    panel: PanelData,
    config: BookBacktestConfig,
    dates: Sequence[dt.date],
) -> _ExecutionContractBinding | None:
    """Fail closed on schedule identity and union-calendar coverage.

    A missing row is an invalid artifact, not a runtime trading-day skip. Every
    panel union date in the requested run window must therefore have one
    explicit row (executable or not) for every declared schedule instrument.
    """
    configured = config.execution_contract_schedule
    if configured is None:
        return None

    # Revalidate from primitives so Pydantic ``model_copy(update=...)`` cannot
    # bypass structural or hash validation on a run-critical artifact.
    schedule = ExecutionContractSchedule.model_validate(
        configured.model_dump(mode="python")
    )
    if config.panel_manifest_sha256 is None:
        raise ValueError(
            "panel_manifest_sha256 is required with an execution contract schedule"
        )
    if config.panel_snapshot != schedule.source_panel_snapshot:
        raise ValueError(
            "execution contract schedule snapshot does not match config panel snapshot"
        )
    if config.panel_manifest_sha256 != schedule.source_panel_manifest_sha256:
        raise ValueError(
            "execution contract schedule manifest hash does not match config pin"
        )
    if config.start < schedule.start or config.end > schedule.end:
        raise ValueError("execution contract schedule does not cover the run window")

    panel_calendar = tuple(panel.calendar)
    if (
        any(not isinstance(date, dt.date) for date in panel_calendar)
        or tuple(sorted(set(panel_calendar))) != panel_calendar
    ):
        raise ValueError(
            "book panel calendar must contain unique, strictly increasing dates"
        )
    expected_run_dates = tuple(
        date for date in panel_calendar if config.start <= date <= config.end
    )
    if tuple(dates) != expected_run_dates:
        raise ValueError("book run dates are inconsistent with the panel union calendar")
    if dates[0] != config.start or dates[-1] != config.end:
        raise ValueError(
            "strict execution contract schedule run bounds must be exact panel "
            "union sessions; "
            f"requested={config.start.isoformat()}..{config.end.isoformat()}, "
            f"resolved={dates[0].isoformat()}..{dates[-1].isoformat()}"
        )

    panel_snapshot = getattr(panel, "snapshot_version", None)
    if panel_snapshot != config.panel_snapshot:
        raise ValueError(
            "book panel snapshot does not match the execution contract schedule: "
            f"panel={panel_snapshot!r}, schedule={schedule.source_panel_snapshot!r}"
        )
    panel_manifest = getattr(panel, "manifest", None)
    if (
        panel_manifest is not None
        and getattr(panel_manifest, "version", None) != panel_snapshot
    ):
        raise ValueError("book panel manifest version and snapshot_version are inconsistent")

    snapshot_dir = getattr(panel, "snapshot_dir", None)
    if snapshot_dir is not None:
        manifest_path = Path(snapshot_dir) / "manifest.json"
        if not manifest_path.is_file():
            raise ValueError(
                f"book panel snapshot is missing manifest.json: {manifest_path}"
            )
        actual_manifest_sha256 = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
        if actual_manifest_sha256 != schedule.source_panel_manifest_sha256:
            raise ValueError(
                "book panel manifest bytes do not match the execution contract "
                f"schedule: expected {schedule.source_panel_manifest_sha256}, "
                f"got {actual_manifest_sha256}"
            )

    panel_instruments = tuple(panel.instruments)
    normalized_panel_instruments = tuple(
        str(instrument).strip().lower() for instrument in panel_instruments
    )
    if (
        panel_instruments != normalized_panel_instruments
        or len(set(panel_instruments)) != len(panel_instruments)
    ):
        raise ValueError("book panel instruments must be unique normalized identifiers")
    unknown_instruments = sorted(set(schedule.instruments).difference(panel_instruments))
    if unknown_instruments:
        raise ValueError(
            "execution contract schedule declares instruments absent from the panel: "
            f"{unknown_instruments}"
        )

    rows = schedule.row_map()
    expected_keys = {
        (date, instrument)
        for date in dates
        for instrument in schedule.instruments
    }
    actual_keys = {
        key
        for key in rows
        if config.start <= key[0] <= config.end
    }
    missing = sorted(expected_keys.difference(actual_keys))
    extra = sorted(actual_keys.difference(expected_keys))
    if missing or extra:
        raise ValueError(
            "execution contract schedule row coverage does not match panel union "
            f"calendar; missing={_format_schedule_keys(missing)}, "
            f"extra={_format_schedule_keys(extra)}"
        )
    return _ExecutionContractBinding(schedule=schedule, rows=rows)


def _format_schedule_keys(keys: Sequence[tuple[dt.date, str]]) -> str:
    rendered = [f"{date.isoformat()}:{instrument}" for date, instrument in keys[:5]]
    if len(keys) > 5:
        rendered.append(f"...+{len(keys) - 5}")
    return repr(rendered)


def _execution_contract_schedule_bound_event(
    schedule: ExecutionContractSchedule,
    config: BookBacktestConfig,
    first_panel_date: dt.date,
) -> dict:
    return {
        "date": first_panel_date.isoformat(),
        "type": "execution_contract_schedule_bound",
        "detail": {
            "sha256": schedule.sha256,
            "source_panel_snapshot": schedule.source_panel_snapshot,
            "source_panel_manifest_sha256": schedule.source_panel_manifest_sha256,
            "selection_rule": schedule.selection_rule,
            "availability_assumption": schedule.availability_assumption,
            "schedule_window": {
                "start": schedule.start.isoformat(),
                "end": schedule.end.isoformat(),
            },
            "run_window": {
                "start": config.start.isoformat(),
                "end": config.end.isoformat(),
            },
            "instruments": list(schedule.instruments),
        },
    }


def _required_execution_contract_row(
    rows: Mapping[tuple[dt.date, str], ExecutionContractScheduleRow],
    fill_date: dt.date,
    instrument: str,
) -> ExecutionContractScheduleRow:
    try:
        return rows[(fill_date, instrument)]
    except KeyError as exc:
        raise ValueError(
            "execution contract schedule preflight invariant violated: missing row "
            f"for {fill_date.isoformat()} {instrument}"
        ) from exc


def _validate_target_schedule_scope(
    targets: Mapping[str, float], declared_instruments: Sequence[str]
) -> None:
    declared = set(declared_instruments)
    outside: list[str] = []
    for raw_instrument, raw_target in targets.items():
        instrument = str(raw_instrument).lower()
        target = float(raw_target)
        if instrument not in declared and (
            not math.isfinite(target) or abs(target) > 1e-12
        ):
            outside.append(str(raw_instrument))
    if outside:
        raise ValueError(
            "nonzero targets fall outside execution contract schedule instruments: "
            f"{sorted(outside)}"
        )


def _validate_returned_contract_bar(
    bar: Any,
    instrument: str,
    expected_contract: str,
    fill_date: dt.date,
) -> None:
    try:
        actual_contract = str(bar["contract"])
    except (KeyError, TypeError) as exc:
        raise ValueError(
            f"contract_bar returned a row without contract identity for {instrument} "
            f"on {fill_date.isoformat()}"
        ) from exc
    if actual_contract != expected_contract:
        raise ValueError(
            "contract_bar returned the wrong contract for strict execution: "
            f"expected {expected_contract}, got {actual_contract} ({instrument}, "
            f"{fill_date.isoformat()})"
        )
    raw_date = None
    if hasattr(bar, "get"):
        raw_date = bar.get("date")
    if raw_date is None:
        raw_date = getattr(bar, "name", None)
    if isinstance(raw_date, pd.Timestamp):
        actual_date = raw_date.date()
    elif isinstance(raw_date, dt.datetime):
        actual_date = raw_date.date()
    elif isinstance(raw_date, dt.date):
        actual_date = raw_date
    elif isinstance(raw_date, str):
        try:
            actual_date = dt.date.fromisoformat(raw_date)
        except ValueError as exc:
            raise ValueError(
                "contract_bar returned a row with an invalid date identity for "
                f"{instrument}: {raw_date!r}"
            ) from exc
    else:
        raise ValueError(
            "contract_bar returned a row without exact date identity for "
            f"{instrument} on {fill_date.isoformat()}"
        )
    if actual_date != fill_date:
        raise ValueError(
            "contract_bar returned a stale or future row for strict execution: "
            f"expected {fill_date.isoformat()}, got {actual_date.isoformat()} "
            f"({instrument}, {expected_contract})"
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
    if not hasattr(view, "current_bar"):
        raise TypeError("book view must implement current_bar for position valuation")
    current_main = view.current_bar(instrument)
    if current_main is not None and str(current_main["contract"]) == str(contract):
        return current_main
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
