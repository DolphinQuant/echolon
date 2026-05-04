"""
Portfolio Trading Runner
========================

Main orchestrator for multi-instrument, multi-strategy parallel trading.

Long-running process that:
- Connects one MiniQMTClient (shared across all slots)
- Schedules daily trading jobs via APScheduler
- Runs per-slot initialize → execute → order fire → fill process → reconcile
- Persists state atomically per slot

Phases per daily cycle:
0. Group slots by (instrument, bar_size), run data pipeline + indicator union
1. Per-slot initialize (failure isolation)
2. Per-slot execute_bar (skip errored)
2.5. Central order firing (deferred execution burst)
3. Process fills (wait callbacks, update VP, log)
3.5. Reconciliation (Level 1 + 2)
4. Portfolio risk check
5. Dashboard
6. Health report + reschedule
"""

import json
import os
import signal
import threading
import time
import traceback
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pytz
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.date import DateTrigger

try:
    from xtquant import xtconstant
except ImportError:
    xtconstant = None  # Available only on QMT-enabled machines

from ..config.deploy_config import QMTAccountConfig
from ..config.portfolio_deploy_config import PortfolioDeployConfig, SlotConfig
from ..config.logging_config import get_deploy_logger, init_logging, shutdown_logging
try:
    from ..platforms.miniqmt.qmt_client import MiniQMTClient
except ImportError:
    MiniQMTClient = None  # Available only on QMT-enabled machines

from echolon.data.loaders.contract_loader import get_main_contract
from echolon.strategy.interfaces import Order, OrderIntent, OrderStatus
from ..slot.capital_slot import CapitalSlot
from ..slot.trading_slot import TradingSlot
from ..slot.risk_overlay import PortfolioRiskOverlay
from echolon.data.loaders.calendar_loader import (
    get_trading_dates,
    is_trading_day,
    is_night_market_open,
)
from echolon.config.markets.factory import MarketFactory
from echolon.data.live_data import run_live_data_update
from echolon.indicators.run import run_indicator_calculation

import logging

logger = logging.getLogger(__name__)

# QMT order status codes
_STATUS_MAP = {
    48: 'UNREPORTED', 49: 'WAIT_REPORTING', 50: 'SUBMITTED',
    55: 'PARTIAL_FILLED', 56: 'FILLED',
    53: 'PARTIAL_CANCELED', 54: 'CANCELED', 57: 'REJECTED',
}


class PortfolioTradingRunner:
    """
    Multi-slot trading orchestrator.

    Manages N TradingSlots on one shared QMT connection.
    """

    TIMEZONE = pytz.timezone("Asia/Shanghai")

    # Default base directory for all deploy runtime data
    DEFAULT_DEPLOY_DIR = os.path.join("workspace", "deploy")

    def __init__(self, config: PortfolioDeployConfig, deploy_data_dir: str = None):
        self.config = config
        self.deploy_data_dir = deploy_data_dir or self.DEFAULT_DEPLOY_DIR

        # Structured subdirectories
        self.slots_dir = os.path.join(self.deploy_data_dir, "slots")
        self.portfolio_dir = os.path.join(self.deploy_data_dir, "portfolio")
        self.logs_dir = os.path.join(self.deploy_data_dir, "logs")

        # Shared QMT client
        self.client: Optional[MiniQMTClient] = None

        # Slots — each gets workspace/deploy/slots/{slot_id}/
        self.slots: List[TradingSlot] = []
        for sc in config.get_enabled_slots():
            self.slots.append(TradingSlot(slot_config=sc, deploy_data_dir=self.slots_dir))

        # Risk overlay — writes to workspace/deploy/portfolio/
        self.risk_overlay = PortfolioRiskOverlay(
            max_portfolio_drawdown_pct=config.deploy.max_portfolio_drawdown_pct,
            deploy_data_dir=self.portfolio_dir,
        )

        # Scheduling
        self.scheduler: Optional[BackgroundScheduler] = None
        self.running = False
        self.shutdown_event = threading.Event()
        self.present_date = datetime.now()

        # Callback routing: real_order_id -> {slot_id, order, event, ...}
        self._order_events: Dict[int, Dict[str, Any]] = {}
        self._unmapped_callbacks: List[Dict[str, Any]] = []
        self._callback_lock = threading.Lock()

        # seq_id -> real order_id mapping (from on_order_stock_async_response)
        self._seq_to_order_id: Dict[int, int] = {}

        # Per-slot order mapping: slot_id -> [(Order, qmt_order_id)]
        self._slot_order_map: Dict[str, List[Tuple[Order, Optional[int]]]] = {}

        # Logging
        init_logging(self.logs_dir)
        self.log = get_deploy_logger("portfolio_runner")

    # =========================================================================
    # Public API
    # =========================================================================

    def run(self) -> None:
        """Main entry: connect, schedule, block until shutdown."""
        self.log.info("=" * 70)
        self.log.info("STARTING PORTFOLIO TRADING RUNNER")
        self.log.info(f"Slots: {[s.slot_id for s in self.slots]}")
        active = self.config.get_active_account()
        self.log.info(
            f"Account: {active.account_id} "
            f"({'TEST' if self.config.account.use_test_account else 'LIVE'})"
        )
        self.log.info("=" * 70)

        self.running = True

        original_sigint = signal.getsignal(signal.SIGINT)
        original_sigterm = signal.getsignal(signal.SIGTERM)
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

        try:
            self._connect_client()
            self.risk_overlay.load(active_slot_ids=[s.slot_id for s in self.slots])
            self._schedule_daily_trading()

            while self.running and not self.shutdown_event.is_set():
                self.shutdown_event.wait(timeout=60)
        except Exception as e:
            self.log.error(f"Fatal error: {e}\n{traceback.format_exc()}")
        finally:
            signal.signal(signal.SIGINT, original_sigint)
            signal.signal(signal.SIGTERM, original_sigterm)
            self.stop()

    def run_single_cycle(self) -> Dict[str, Any]:
        """Execute a single trading cycle for testing."""
        self.log.info("Running single portfolio cycle (test mode)")
        self.running = True
        try:
            self._connect_client()
            self._ensure_trading_calendars()
            self.risk_overlay.load(active_slot_ids=[s.slot_id for s in self.slots])
            return self._market_open_job_inner()
        except Exception as e:
            self.log.error(f"Single cycle failed: {e}\n{traceback.format_exc()}")
            return {"status": "error", "error": str(e)}
        finally:
            self.running = False

    def stop(self) -> None:
        """Graceful shutdown."""
        if not self.running and self.shutdown_event.is_set():
            return

        self.log.info("Initiating graceful shutdown...")
        self.running = False
        self.shutdown_event.set()

        # Finalize per-slot strategy loggers
        for slot in self.slots:
            if slot.strategy and hasattr(slot.strategy, 'strategy_logger'):
                try:
                    sl = slot.strategy.strategy_logger
                    if sl:
                        sl.finalize_logging()
                except Exception as e:
                    self.log.error(f"[{slot.slot_id}] Logger finalize error: {e}")

        if self.client:
            try:
                self.client.disconnect()
            except Exception:
                pass
            self.client = None

        if self.scheduler:
            try:
                self.scheduler.shutdown(wait=False)
            except Exception:
                pass
            self.scheduler = None

        self.risk_overlay.save()
        shutdown_logging()

    # =========================================================================
    # Connection
    # =========================================================================

    def _connect_client(self) -> None:
        """Create and connect shared MiniQMTClient."""
        account_cfg = self.config.get_active_account()
        # Use first slot's instrument for the MiniQMTClient init
        first_slot = self.slots[0].slot_config if self.slots else None
        market = first_slot.market if first_slot else "SHFE"
        asset = first_slot.instrument if first_slot else "aluminum"

        self.client = MiniQMTClient(
            config=account_cfg,
            market=market,
            asset=asset,
        )
        connected = self.client.connect()
        if connected:
            self.log.info("QMT connection established")
            self.client.set_callbacks(
                order_callback=self._on_order_update,
                trade_callback=self._on_trade_update,
                async_response_callback=self._on_async_response,
            )
        else:
            self.log.warning("QMT connection failed (may be outside trading hours)")

    # =========================================================================
    # Scheduling
    # =========================================================================

    def _schedule_daily_trading(self) -> None:
        """Schedule first daily job using trading calendar."""
        self.scheduler = BackgroundScheduler(timezone=self.TIMEZONE)

        # Use first slot for calendar checks
        first = self.slots[0].slot_config if self.slots else None
        if not first:
            self.log.error("No slots configured")
            return

        # Ensure trading calendars exist before any is_trading_day() call
        self._ensure_trading_calendars()

        today = datetime.now()
        market, instrument = first.market, first.instrument

        target_date = None
        if is_trading_day(market, instrument, today):
            hour, minute = self._get_schedule_time(today, market, instrument)
            trigger_time = today.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if today < trigger_time:
                target_date = today

        if target_date is None:
            target_date = self._find_next_trading_day(today, market, instrument)

        if target_date is None:
            self.log.error("No future trading days found")
            return

        hour, minute = self._get_schedule_time(target_date, market, instrument)
        run_date = self.TIMEZONE.localize(
            target_date.replace(hour=hour, minute=minute, second=0, microsecond=0)
        )

        self.scheduler.add_job(
            self._market_open_job,
            trigger=DateTrigger(run_date=run_date),
            name="PortfolioDailyJob",
            misfire_grace_time=self.config.deploy.misfire_grace_time,
        )
        self.scheduler.start()
        self.log.info(f"Scheduled: {target_date.strftime('%Y-%m-%d')} at {hour:02d}:{minute:02d}")

    def _market_open_job(self) -> None:
        """APScheduler job entry point."""
        self.log.info("=" * 70)
        self.log.info("PORTFOLIO DAILY JOB TRIGGERED")
        self.log.info("=" * 70)

        if not self.running:
            return

        self._ensure_trading_calendars()

        first = self.slots[0].slot_config
        if not is_trading_day(first.market, first.instrument, datetime.now()):
            self.log.info("Not a trading day, skipping")
            self._reschedule_next_job()
            return

        self.present_date = datetime.now()

        try:
            self._market_open_job_inner()
        except Exception as e:
            self.log.error(f"Daily cycle failed: {e}\n{traceback.format_exc()}")

        self._reschedule_next_job()

    def _market_open_job_inner(self) -> Dict[str, Any]:
        """Core daily cycle logic."""
        cycle_start = datetime.now()
        results: Dict[str, Any] = {"status": "success", "timestamp": cycle_start.isoformat()}

        # Clear stale state
        self._order_events.clear()
        self._unmapped_callbacks.clear()
        self._slot_order_map.clear()
        for slot in self.slots:
            slot.reset_daily_state()

        # Phase 0: Data pipeline per (instrument, bar_size) group
        self._phase0_data_pipeline()

        # Phase 1: Per-slot initialize (failure isolation)
        calendar_path = self._get_calendar_path()
        for slot in self.slots:
            try:
                slot.initialize(self.present_date, calendar_path=calendar_path)
                # Set client on engine
                if self.client:
                    slot.engine.set_client(self.client)
            except Exception as e:
                slot.mark_error(f"Init failed: {e}")
                self.log.error(f"[{slot.slot_id}] Init failed:\n{traceback.format_exc()}")

        # Phase 2: Per-slot execute_bar
        for slot in self.slots:
            if slot.is_errored:
                continue
            try:
                slot.execute_bar()
                self.log.info(f"[{slot.slot_id}] execute_bar complete")
                # Surface the strategy's decision (entry/exit reason) so the
                # operator can understand WHY an order was queued before it
                # is actually fired during the night-market open.  Goes to
                # both terminal and qts_system.log via the runner logger.
                self._log_strategy_decision(slot)
            except Exception as e:
                slot.mark_error(f"execute_bar failed: {e}")
                self.log.error(f"[{slot.slot_id}] execute_bar failed:\n{traceback.format_exc()}")

        # Phase 2.5: Central order firing
        self._execute_pending_orders()

        # Phase 3: Process fills
        self._process_fills()

        # Phase 3.5: Reconciliation
        if self.client:
            try:
                self.risk_overlay.verify_todays_trades(self.client, self.slots)
                self.risk_overlay.cross_check_aggregate(self.client, self.slots)
            except Exception as e:
                self.log.error(f"Reconciliation failed: {e}")

        # Phase 4: Portfolio risk check
        dd_ok = self.risk_overlay.check_portfolio_drawdown(self.slots)
        if not dd_ok:
            self.log.error("PORTFOLIO DRAWDOWN LIMIT BREACHED — manual intervention required")
            results["drawdown_breached"] = True

        # Phase 5: Save trading data snapshot + state + health report
        from ..io.data_logger import save_trading_data_snapshot
        for slot in self.slots:
            if not slot.is_errored:
                # Save daily trading data snapshot (equity curve source)
                try:
                    sc = slot.slot_config
                    trade_data_dir = os.path.join(self.slots_dir, sc.slot_id)
                    md = slot.engine.get_market_data()
                    position = slot.portfolio.get_position()
                    # Extract signal data from strategy logger
                    # Combines entry and exit decisions into a single signal_type
                    sig_type = None
                    sig_strength = 0.0
                    sig_reason = None
                    strat_logger = getattr(slot.strategy, 'strategy_logger', None) if slot.strategy else None
                    if strat_logger and hasattr(strat_logger, 'current_bar_data'):
                        cbd = strat_logger.current_bar_data
                        if cbd.get('exit_should_exit'):
                            sig_type = 'EXIT'
                            sig_strength = 1.0
                            sig_reason = cbd.get('exit_reason', '')
                        else:
                            sig_type = cbd.get('entry_signal')
                            sig_strength = cbd.get('entry_strength', 0.0)
                            sig_reason = cbd.get('entry_reason')

                    # Determine last action from today's fills
                    last_action = 'NO_ACTION'
                    last_action_price = 0.0
                    last_action_size = 0
                    if slot.todays_processed_fills:
                        last_fill = slot.todays_processed_fills[-1]
                        last_action = last_fill.get('intent', 'NO_ACTION')
                        last_action_price = last_fill.get('price', 0.0)
                        last_action_size = last_fill.get('volume', 0)

                    save_trading_data_snapshot(
                        trading_data_dir=trade_data_dir,
                        market_data={
                            'current_price': md.get_current_price(),
                            'daily_open': md.get_open(),
                            'daily_high': md.get_high(),
                            'daily_low': md.get_low(),
                            'volume': md.get_volume(),
                        },
                        signal_data={
                            'signal_type': sig_type,
                            'signal_strength': sig_strength,
                            'signal_confidence': 0.0,
                            'signal_reason': sig_reason,
                        },
                        position_data={
                            'current_position_size': int(position.size) if position else 0,
                            'current_position_avg_price': position.avg_price if position else None,
                            'unrealized_pnl': slot.portfolio.get_unrealized_pnl(),
                        },
                        account_data={
                            'available_cash': slot.capital_slot.available_cash,
                            'total_account_value': slot.capital_slot.equity,
                        },
                        performance_data={
                            'daily_pnl': 0.0,
                            'total_pnl': slot.capital_slot.realized_pnl,
                            'win_rate': 0.0,
                            'trade_count': getattr(slot.strategy, 'total_trades', 0) if slot.strategy else 0,
                        },
                        symbol=sc.instrument,
                        action_contract=slot.trading_contract if last_action != 'NO_ACTION' else '',
                        position_contract=position.symbol if position and position.size != 0 else '',
                        position_direction=position.direction if position and position.size != 0 else '',
                        last_trade_action={
                            'action': last_action,
                            'price': last_action_price,
                            'size': last_action_size,
                        } if last_action != 'NO_ACTION' else None,
                    )
                except Exception as e:
                    self.log.error(f"[{slot.slot_id}] Trading data snapshot failed: {e}")

                try:
                    slot.save_state()
                except Exception as e:
                    self.log.error(f"[{slot.slot_id}] State save failed: {e}")

            # Finalize strategy logger
            if slot.strategy and hasattr(slot.strategy, 'strategy_logger') and slot.strategy.strategy_logger:
                try:
                    slot.strategy.strategy_logger.finalize_logging()
                except Exception as e:
                    self.log.error(f"[{slot.slot_id}] Logger finalize failed: {e}")

        self.risk_overlay.save()

        # Phase 6: Dashboard (after data save so files exist)
        try:
            self._generate_dashboard()
        except Exception as e:
            self.log.error(f"Dashboard generation failed: {e}")

        self._save_health_report(cycle_start, results)

        duration = (datetime.now() - cycle_start).total_seconds()
        results["duration_seconds"] = duration
        self.log.info(f"Portfolio cycle completed in {duration:.1f}s")

        from echolon._internal.atomic_state import update_heartbeat
        update_heartbeat(
            workspace_deploy_dir=self.deploy_data_dir,
            slots_alive=[s.slot_id for s in self.slots],
        )

        return results

    # =========================================================================
    # Decision logging
    # =========================================================================

    def _log_strategy_decision(self, slot: TradingSlot) -> None:
        """Log the strategy's per-bar entry/exit decision via the runner logger.

        Reads from the strategy's CSVStrategyLogger ``current_bar_data`` so the
        same fields that land in ``qmt_<instrument>.csv`` (entry_signal,
        entry_reason, exit_should_exit, exit_reason, risk reasons, etc.) are
        also surfaced in ``qts_system.log`` and the terminal at execute_bar
        time — i.e. before the night market opens and orders are fired.

        Defensive against missing logger / missing fields: this is best-effort
        diagnostic output and must never raise.
        """
        try:
            strategy = getattr(slot, 'strategy', None)
            slogger = getattr(strategy, 'strategy_logger', None) if strategy else None
            bar = getattr(slogger, 'current_bar_data', None) if slogger else None
            if not bar:
                return

            entry_signal = bar.get('entry_signal', 'HOLD')
            entry_reason = bar.get('entry_reason', '')
            should_exit = bar.get('exit_should_exit', False)
            exit_reason = bar.get('exit_reason', '')
            risk_allowed = bar.get('risk_trading_allowed', '')
            risk_reason = bar.get('risk_reason', '')
            position = bar.get('capital_position_size', 0.0)

            self.log.info(
                f"[{slot.slot_id}] DECISION: position={position} "
                f"risk_allowed={risk_allowed} | "
                f"entry={entry_signal} | exit_triggered={should_exit}"
            )
            if exit_reason:
                self.log.info(f"[{slot.slot_id}]   exit_reason: {exit_reason}")
            if entry_reason:
                self.log.info(f"[{slot.slot_id}]   entry_reason: {entry_reason}")
            if risk_reason:
                self.log.info(f"[{slot.slot_id}]   risk_reason: {risk_reason}")
        except Exception as e:
            # Never let decision-logging break the cycle.
            self.log.warning(f"[{slot.slot_id}] _log_strategy_decision failed: {e}")

    # =========================================================================
    # Phase 0: Data pipeline
    # =========================================================================

    def _phase0_data_pipeline(self) -> None:
        """Run data pipeline per instrument, then indicators per slot.

        Uses XtdcClient (token-based xtdatacenter) instead of MiniQMTClient
        for the data pipeline. One xtdc session serves all instruments:
        - main_contract.csv download (token-only API)
        - per-contract OHLCV download
        - contract discovery via xtdata

        The xtdc connection is opened once, shared across all instruments,
        and closed after all downloads complete. This avoids the port
        conflict that occurs when separate xtdc sessions are created
        per instrument.
        """
        from echolon.indicators.utils.merge_indicators import (
            load_indicator_list,
            merge_indicator_lists,
        )
        from ..platforms.miniqmt.xtdc_client import XtdcClient

        # Connect XtdcClient once for all instruments
        xtdc = XtdcClient()
        if not xtdc.connect():
            self.log.error("XtdcClient connection failed — data pipeline will be skipped")
            return

        try:
            # Step 1: Data download — once per (instrument, bar_size)
            # XtdcClient provides both download_main_contract_history()
            # (called by extract_main_contract) and get_market_data()
            # (called by _download_single_contract) through one connection.
            groups = self.config.get_slots_by_instrument_and_barsize()
            for (instrument_code, bar_size), slot_configs in groups.items():
                first_sc = slot_configs[0]
                ctx = MarketFactory.create(
                    market=first_sc.market,
                    instrument=first_sc.instrument_code,
                    frequency=first_sc.frequency,
                    bar_size=first_sc.bar_size,
                )
                self.log.info(f"Data download: {instrument_code}/{bar_size}")
                try:
                    run_live_data_update(
                        ctx=ctx,
                        client=xtdc,
                        present_date=self.present_date,
                        trading_calendar_path=self.config.deploy.trading_calendar_path,
                        skip_calendar=True,
                    )
                except Exception as e:
                    self.log.error(f"Data download failed for {instrument_code}/{bar_size}: {e}")
        finally:
            xtdc.disconnect()

        # Build PathsConfig once outside the loop
        from echolon.config.paths_config import PathsConfig
        paths = PathsConfig.from_env()
        indicators_backtest_dir = paths.indicators_backtest_dir

        end_date = (
            self.present_date.strftime("%Y-%m-%d")
            if hasattr(self.present_date, "strftime")
            else str(self.present_date)
        )

        # Step 2: Indicator calculation — merge per-(instrument, bar_size) group,
        # compute the union once, output to a shared dir. trading_slot's
        # _get_indicators_path resolves this group dir after its per-slot check.
        groups = self.config.get_slots_by_instrument_and_barsize()
        for (instrument_code, bar_size), slot_configs in groups.items():
            group_id = f"{instrument_code}_{bar_size}"
            group_dir = os.path.join(str(indicators_backtest_dir), group_id)

            # Collect each slot's flat-dict indicator_list + regime_params
            # (read from calculator_params.json).
            from echolon._internal.strategy_files import get_regime_params
            slot_configs_with_ind = []
            for sc in slot_configs:
                ind_path = os.path.join(sc.strategy_code_dir, "strategy_indicator_list.json")
                if not os.path.exists(ind_path):
                    self.log.warning(f"[{sc.slot_id}] skipped: no {ind_path}")
                    continue
                ind = load_indicator_list(ind_path)
                rp = get_regime_params(sc.strategy_code_dir)
                slot_configs_with_ind.append((sc, ind, rp))

            if not slot_configs_with_ind:
                self.log.warning(f"Indicators skipped for group {group_id}: no slot has a list")
                continue

            # Union indicator_lists across slots in this group
            merged_indicator_list = merge_indicator_lists(
                [ind for (_, ind, _) in slot_configs_with_ind]
            )

            # Regime params: take the first slot's. Warn if any other slot in
            # the group has a different set (divergent regime_params would need
            # per-slot compute; deferred until that case actually appears).
            regime_params = next(
                (rp for (_, _, rp) in slot_configs_with_ind if rp is not None),
                None,
            )
            if regime_params is not None:
                for (sc, _, rp) in slot_configs_with_ind:
                    if rp is not None and rp != regime_params:
                        self.log.warning(
                            f"[{sc.slot_id}] regime_params differ within group {group_id}; "
                            f"using first slot's params (falling back to per-slot compute "
                            f"is not yet implemented)"
                        )

            # Window: earliest start_date across the group (for backfill)
            start_dates = [
                getattr(sc, "start_date", None)
                for (sc, _, _) in slot_configs_with_ind
            ]
            start_dates = [d for d in start_dates if d]
            start_date = min(start_dates) if start_dates else None

            first_sc = slot_configs_with_ind[0][0]
            ctx = MarketFactory.create(
                market=first_sc.market,
                instrument=first_sc.instrument_code,
                frequency=first_sc.frequency,
                bar_size=first_sc.bar_size,
            )

            self.log.info(
                f"Indicators: {group_id} "
                f"({len(slot_configs_with_ind)} slot(s), "
                f"{len(merged_indicator_list)} unique indicators) -> {group_dir}"
            )
            try:
                run_indicator_calculation(
                    ctx=ctx,
                    output_dir=group_dir,
                    indicator_list=merged_indicator_list,
                    use_parallel=True,
                    regime_params=regime_params,
                    start_date=start_date,
                    end_date=end_date,
                )
            except Exception as e:
                self.log.error(f"Indicators failed for group {group_id}: {e}")

    # =========================================================================
    # Phase 2.5: Central order firing
    # =========================================================================

    def _execute_pending_orders(self) -> None:
        """
        Collect all pending orders from non-errored slots, fire via QMT.

        Uses order_stock_async for burst-fire, then maps qmt_order_ids back.
        """
        if self.client is None:
            self.log.warning("No client — orders will not be executed")
            return

        all_pending: List[Tuple[TradingSlot, Order]] = []
        for slot in self.slots:
            if slot.is_errored:
                continue
            for order in slot.get_pending_orders():
                all_pending.append((slot, order))

        if not all_pending:
            self.log.info("No pending orders to execute")
            return

        # Per-slot pending order detail — makes the source of each queued
        # order unambiguous in qts_system.log.  Without this, "Firing N
        # orders" alone does not identify which slots produced them.
        self.log.info(f"Pending orders breakdown ({len(all_pending)} total):")
        for slot, order in all_pending:
            intent_str = order.intent.value if order.intent else "UNKNOWN"
            price_str = f"{order.price}" if order.price is not None else "MARKET"
            self.log.info(
                f"  [{slot.slot_id}] {intent_str} size={int(order.size)} "
                f"price={price_str} contract={order.symbol}"
            )

        self.log.info(f"Firing {len(all_pending)} orders")

        # Subscribe tick data for all pending order symbols BEFORE the
        # central wait. By the time night market opens (21:00), the tick
        # cache will have ~18 minutes of warm data for price resolution.
        subscribed = set()
        for slot, order in all_pending:
            sym = order.symbol
            if sym not in subscribed:
                self.client.subscribe_tick(sym)
                subscribed.add(sym)

        # Central wait for night market open (21:00 CST)
        self._central_wait_if_night_market()

        for slot, order in all_pending:
            slot_id = slot.slot_id
            try:
                # Use async API for parallel burst-fire — all orders hit
                # QMT within ~50ms instead of sequential blocking.
                # Night market timing is handled centrally by
                # _central_wait_if_night_market() above.
                intent_str = order.intent.value if order.intent else "ENTRY_LONG"
                qmt_order_id = self.client.submit_order_async(
                    symbol=order.symbol,
                    volume=int(order.size),
                    price=order.price,
                    order_type="MARKET",
                    intent=intent_str,
                    strategy_name=slot_id,
                )

                if qmt_order_id is not None and qmt_order_id > 0:
                    order.status = OrderStatus.SUBMITTED
                    order.metadata['qmt_order_id'] = qmt_order_id

                    # Register for callback routing
                    with self._callback_lock:
                        self._order_events[qmt_order_id] = {
                            'slot_id': slot_id,
                            'order': order,
                            'event': threading.Event(),
                            'status': 0,
                            'traded_price': 0.0,
                            'traded_volume': 0,
                        }

                    if slot_id not in self._slot_order_map:
                        self._slot_order_map[slot_id] = []
                    self._slot_order_map[slot_id].append((order, qmt_order_id))

                    self.log.info(
                        f"[{slot_id}] Order fired: {order.intent.value} "
                        f"{order.size}@{order.price} -> qmt_id={qmt_order_id}"
                    )
                else:
                    order.status = OrderStatus.REJECTED
                    self.log.error(f"[{slot_id}] Order rejected by QMT: {order.intent.value}")

            except Exception as e:
                order.status = OrderStatus.REJECTED
                self.log.error(f"[{slot_id}] Order fire error: {e}")

        # Flush any callbacks that arrived before mapping was set up
        self._flush_unmapped_callbacks()

    # =========================================================================
    # Phase 3: Process fills
    # =========================================================================

    def _process_fills(self, timeout: float = 600.0) -> None:
        """
        Wait for fill callbacks and update VP for each slot.

        For each submitted order, waits up to timeout for callback,
        then updates SlotAwarePortfolio.
        """
        for slot_id, order_list in self._slot_order_map.items():
            slot = self._get_slot_by_id(slot_id)
            if slot is None or slot.is_errored:
                continue

            for order, seq_id in order_list:
                if seq_id is None:
                    continue

                # Translate seq_id to real order_id (mapped by _on_async_response)
                real_id = self._seq_to_order_id.get(seq_id, seq_id)
                entry = self._order_events.get(real_id)
                if entry is None:
                    self.log.warning(f"[{slot_id}] No entry for seq={seq_id}/order={real_id}")
                    continue

                self.log.info(f"[{slot_id}] Waiting for fill on order_id={real_id} (seq={seq_id})...")
                filled = entry['event'].wait(timeout=timeout)

                # Grace period: on_stock_trade callback with price/volume may
                # arrive slightly after on_stock_order sets status=56.
                # Wait up to 2s for the trade callback to populate price.
                if filled and entry['status'] == 56 and entry['traded_price'] == 0.0:
                    for _ in range(20):  # 20 x 0.1s = 2s max
                        time.sleep(0.1)
                        if entry['traded_price'] > 0:
                            break

                status = entry['status']
                traded_price = entry['traded_price']
                traded_volume = entry['traded_volume']
                exec_status = _STATUS_MAP.get(status, f'UNKNOWN_{status}')

                if not filled:
                    self.log.warning(
                        f"[{slot_id}] Timeout waiting for order_id={real_id}"
                    )
                    continue

                self.log.info(
                    f"[{slot_id}] Fill: status={exec_status}, "
                    f"price={traded_price}, volume={traded_volume}"
                )

                if status == 56 and traded_volume > 0:  # FILLED
                    # Safety: resolve traded_price if still 0.0
                    if traded_price <= 0:
                        traded_price = self._resolve_fill_price(real_id, slot_id)

                    if traded_price <= 0:
                        self.log.error(
                            f"[{slot_id}] CRITICAL: Fill price unresolvable for "
                            f"order_id={real_id}. Skipping VP update to prevent "
                            f"capital corruption. Manual reconciliation required."
                        )
                        slot.todays_processed_fills.append({
                            'qmt_order_id': real_id,
                            'slot_id': slot_id,
                            'intent': order.intent.value if order.intent else '',
                            'price': 0.0,
                            'volume': traded_volume,
                            'timestamp': datetime.now().isoformat(),
                            'error': 'PRICE_UNKNOWN',
                        })
                        continue

                    order.status = OrderStatus.FILLED
                    order.filled_price = traded_price
                    order.filled_size = traded_volume

                    # Update VP and log trade
                    try:
                        prev_pos = slot.portfolio.get_position()
                        prev_size = int(prev_pos.size) if prev_pos else 0
                        prev_avg = prev_pos.avg_price if prev_pos else 0.0
                        prev_realized = slot.capital_slot.realized_pnl

                        self._apply_fill_to_vp(slot, order, traded_price, traded_volume)

                        cur_pos = slot.portfolio.get_position()
                        cur_size = int(cur_pos.size) if cur_pos else 0
                        cur_avg = cur_pos.avg_price if cur_pos else 0.0
                        # Per-trade realized P&L = delta in cumulative realized
                        trade_realized_pnl = slot.capital_slot.realized_pnl - prev_realized

                        slot.todays_processed_fills.append({
                            'qmt_order_id': real_id,
                            'slot_id': slot_id,
                            'intent': order.intent.value if order.intent else '',
                            'price': traded_price,
                            'volume': traded_volume,
                            'timestamp': datetime.now().isoformat(),
                        })

                        # Update strategy logger with fill result
                        if slot.strategy and hasattr(slot.strategy, 'strategy_logger') and slot.strategy.strategy_logger:
                            slot.strategy.strategy_logger.log_order_event({
                                'action': 'executed',
                                'ref': order.metadata.get('internal_ref', ''),
                                'execution_price': traded_price,
                                'executed_size': traded_volume,
                                'execution_date': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                            })

                        # Update strategy trade counters
                        if slot.strategy:
                            slot.strategy.total_trades = getattr(slot.strategy, 'total_trades', 0) + 1

                        # Update top-level StrategyState fields
                        intent = order.intent
                        if intent in (OrderIntent.ENTRY_LONG, OrderIntent.ROLLOVER_OPEN):
                            fill_side = "LONG"
                        elif intent == OrderIntent.ENTRY_SHORT:
                            fill_side = "SHORT"
                        else:
                            fill_side = "FLAT"
                        slot.notify_fill(
                            symbol=order.symbol,
                            side=fill_side,
                            size=traded_volume,
                            price=traded_price,
                            bar_count=getattr(slot.strategy, 'bar_count', 0),
                        )

                        # Write per-slot trade execution CSV
                        from ..io.data_logger import save_trade_execution
                        sc = slot.slot_config
                        trade_data_dir = os.path.join(self.slots_dir, slot_id)
                        save_trade_execution(
                            trading_data_dir=trade_data_dir,
                            order_info={
                                'order_id': str(real_id),
                                'direction': order.intent.value if order.intent else '',
                                'order_type': 'MARKET',
                                'submitted_price': order.price or 0.0,
                                'submitted_size': int(order.size) if order.size else 0,
                            },
                            execution_details={
                                'executed_price': traded_price,
                                'executed_size': traded_volume,
                                'commission': 0.0,
                                'status': exec_status,
                            },
                            position_impact={
                                'position_before': prev_size,
                                'position_after': cur_size,
                                'avg_price_before': prev_avg,
                                'avg_price_after': cur_avg,
                            },
                            pnl_impact={
                                'realized_pnl': trade_realized_pnl,
                                'unrealized_pnl': slot.portfolio.get_unrealized_pnl(),
                            },
                            symbol=sc.instrument,
                        )
                    except Exception as e:
                        self.log.error(f"[{slot_id}] VP update/logging failed: {e}")

                elif status in (53, 54):  # CANCELED
                    order.status = OrderStatus.CANCELLED
                    msg = entry.get('status_msg', '')
                    self.log.warning(f"[{slot_id}] Order canceled: order_id={real_id}, msg={msg}")

                    # Update strategy logger with cancel
                    if slot.strategy and hasattr(slot.strategy, 'strategy_logger') and slot.strategy.strategy_logger:
                        slot.strategy.strategy_logger.log_order_event({
                            'action': 'cancelled',
                            'status': 'Cancelled',
                            'ref': order.metadata.get('internal_ref', ''),
                        })

                    # Record canceled order in today's fills for trading_data snapshot
                    slot.todays_processed_fills.append({
                        'qmt_order_id': real_id,
                        'slot_id': slot_id,
                        'intent': f"CANCELED_{order.intent.value}" if order.intent else 'CANCELED',
                        'price': 0.0,
                        'volume': 0,
                        'timestamp': datetime.now().isoformat(),
                    })

                    # Write canceled trade to execution CSV
                    from ..io.data_logger import save_trade_execution
                    sc = slot.slot_config
                    trade_data_dir = os.path.join(self.slots_dir, slot_id)
                    save_trade_execution(
                        trading_data_dir=trade_data_dir,
                        order_info={
                            'order_id': str(real_id),
                            'direction': order.intent.value if order.intent else '',
                            'order_type': 'MARKET',
                            'submitted_price': order.price or 0.0,
                            'submitted_size': int(order.size) if order.size else 0,
                        },
                        execution_details={
                            'executed_price': 0.0,
                            'executed_size': 0,
                            'commission': 0.0,
                            'status': 'CANCELED',
                        },
                        position_impact={
                            'position_before': 0,
                            'position_after': 0,
                            'avg_price_before': 0.0,
                            'avg_price_after': 0.0,
                        },
                        pnl_impact={
                            'realized_pnl': 0.0,
                            'unrealized_pnl': 0.0,
                        },
                        symbol=sc.instrument,
                    )

                elif status == 57:  # REJECTED
                    order.status = OrderStatus.REJECTED
                    msg = entry.get('status_msg', '')
                    self.log.error(f"[{slot_id}] Order rejected: order_id={real_id}, msg={msg}")

                    # Update strategy logger with rejection
                    if slot.strategy and hasattr(slot.strategy, 'strategy_logger') and slot.strategy.strategy_logger:
                        slot.strategy.strategy_logger.log_order_event({
                            'action': 'rejected',
                            'status': 'Rejected',
                            'ref': order.metadata.get('internal_ref', ''),
                        })

                    # Write rejected trade to execution CSV
                    from ..io.data_logger import save_trade_execution
                    sc = slot.slot_config
                    trade_data_dir = os.path.join(self.slots_dir, slot_id)
                    save_trade_execution(
                        trading_data_dir=trade_data_dir,
                        order_info={
                            'order_id': str(real_id),
                            'direction': order.intent.value if order.intent else '',
                            'order_type': 'MARKET',
                            'submitted_price': order.price or 0.0,
                            'submitted_size': int(order.size) if order.size else 0,
                        },
                        execution_details={
                            'executed_price': 0.0,
                            'executed_size': 0,
                            'commission': 0.0,
                            'status': 'REJECTED',
                        },
                        position_impact={
                            'position_before': 0,
                            'position_after': 0,
                            'avg_price_before': 0.0,
                            'avg_price_after': 0.0,
                        },
                        pnl_impact={
                            'realized_pnl': 0.0,
                            'unrealized_pnl': 0.0,
                        },
                        symbol=sc.instrument,
                    )

    def _resolve_fill_price(self, order_id: int, slot_id: str) -> float:
        """Attempt to resolve a fill price when the trade callback didn't provide one.

        Fallback chain:
        1. Re-check _order_events (trade callback may have arrived late)
        2. Query QMT trade history for the order_id
        3. Return 0.0 if all fail (caller must handle)
        """
        # Tier 1: re-check entry (callback thread may have updated it)
        entry = self._order_events.get(order_id)
        if entry and entry.get('traded_price', 0) > 0:
            price = entry['traded_price']
            self.log.info(f"[{slot_id}] Price resolved (re-check): {price}")
            return price

        # Tier 2: query QMT trade history
        if self.client:
            try:
                trades = self.client.query_stock_trades()
                if trades:
                    for t in trades:
                        tid = t.get('order_id') if isinstance(t, dict) else getattr(t, 'order_id', None)
                        if str(tid) == str(order_id):
                            price = float(t.get('traded_price', 0) if isinstance(t, dict) else getattr(t, 'traded_price', 0))
                            if price > 0:
                                self.log.info(f"[{slot_id}] Price resolved (QMT query): {price}")
                                return price
            except Exception as e:
                self.log.warning(f"[{slot_id}] QMT trade query failed: {e}")

        self.log.error(f"[{slot_id}] Price resolution FAILED for order_id={order_id}")
        return 0.0

    def _apply_fill_to_vp(
        self,
        slot: TradingSlot,
        order: Order,
        price: float,
        volume: float,
    ) -> None:
        """Update SlotAwarePortfolio based on fill."""
        portfolio = slot.portfolio
        intent = order.intent

        if intent in (OrderIntent.ENTRY_LONG, OrderIntent.ROLLOVER_OPEN):
            portfolio.open_position(
                symbol=order.symbol,
                direction="LONG",
                size=volume,
                price=price,
            )
        elif intent == OrderIntent.ENTRY_SHORT:
            portfolio.open_position(
                symbol=order.symbol,
                direction="SHORT",
                size=volume,
                price=price,
            )
        elif intent in (
            OrderIntent.EXIT_LONG, OrderIntent.EXIT_SHORT,
            OrderIntent.FORCED_EXIT, OrderIntent.ROLLOVER_CLOSE,
        ):
            portfolio.close_position(size=volume, price=price)

    # =========================================================================
    # Callbacks (from QMT callback thread)
    # =========================================================================

    def _on_async_response(self, seq_id: int, order_id: int) -> None:
        """Handle order_stock_async response — maps seq_id to real order_id.

        order_stock_async returns a seq_id immediately. The real exchange
        order_id arrives later via this callback. We re-key _order_events
        from seq_id to real order_id so that subsequent _on_order_update
        and _on_trade_update callbacks (which use real order_id) can find
        the entry.
        """
        with self._callback_lock:
            self._seq_to_order_id[seq_id] = order_id
            # Re-key _order_events from seq_id to real order_id
            entry = self._order_events.pop(seq_id, None)
            if entry is not None:
                self._order_events[order_id] = entry
                # Also update the Order metadata
                entry['order'].metadata['qmt_order_id'] = order_id
                self.log.info(
                    f"Async response: seq={seq_id} -> order_id={order_id} "
                    f"(slot={entry['slot_id']})"
                )
            else:
                self.log.warning(
                    f"Async response: seq={seq_id} -> order_id={order_id} "
                    f"(no pending entry found)"
                )

            # Flush any unmapped callbacks that arrived before this mapping
            remaining = []
            for cb in self._unmapped_callbacks:
                cb_entry = self._order_events.get(cb['order_id'])
                if cb_entry is not None:
                    if cb['type'] == 'order':
                        cb_entry['status'] = cb['status']
                        cb_entry['traded_price'] = cb['traded_price']
                        cb_entry['traded_volume'] = cb['traded_volume']
                        if cb['status'] not in (48, 49, 50):
                            cb_entry['event'].set()
                    elif cb['type'] == 'trade' and cb['traded_price'] > 0:
                        cb_entry['traded_price'] = cb['traded_price']
                        cb_entry['traded_volume'] = cb['traded_volume']
                else:
                    remaining.append(cb)
            self._unmapped_callbacks = remaining

    def _on_order_update(self, order) -> None:
        """QMT order status callback. Stores data, signals event on terminal."""
        order_id = getattr(order, 'order_id', 0)
        order_status = getattr(order, 'order_status', 0)
        traded_price = getattr(order, 'traded_price', 0.0)
        traded_volume = getattr(order, 'traded_volume', 0)
        status_msg = getattr(order, 'status_msg', '')

        with self._callback_lock:
            entry = self._order_events.get(order_id)
            if entry is not None:
                entry['status'] = order_status
                entry['traded_price'] = traded_price
                entry['traded_volume'] = traded_volume
                entry['status_msg'] = status_msg
                if order_status not in (48, 49, 50):
                    entry['event'].set()
            else:
                # Unmapped — buffer for later
                self._unmapped_callbacks.append({
                    'type': 'order',
                    'order_id': order_id,
                    'status': order_status,
                    'traded_price': traded_price,
                    'traded_volume': traded_volume,
                    'status_msg': status_msg,
                })

    def _on_trade_update(self, trade) -> None:
        """QMT trade execution callback."""
        trade_id = getattr(trade, 'order_id', 0)
        traded_price = getattr(trade, 'traded_price', 0.0)
        traded_volume = getattr(trade, 'traded_volume', 0)

        with self._callback_lock:
            entry = self._order_events.get(trade_id)
            if entry is not None and traded_price > 0:
                entry['traded_price'] = traded_price
                entry['traded_volume'] = traded_volume
            else:
                self._unmapped_callbacks.append({
                    'type': 'trade',
                    'order_id': trade_id,
                    'traded_price': traded_price,
                    'traded_volume': traded_volume,
                })

    def _flush_unmapped_callbacks(self) -> None:
        """Re-process callbacks that arrived before mapping was registered."""
        with self._callback_lock:
            remaining = []
            for cb in self._unmapped_callbacks:
                order_id = cb['order_id']
                entry = self._order_events.get(order_id)
                if entry is not None:
                    if cb['type'] == 'order':
                        entry['status'] = cb['status']
                        entry['traded_price'] = cb['traded_price']
                        entry['traded_volume'] = cb['traded_volume']
                        if cb['status'] not in (48, 49, 50):
                            entry['event'].set()
                    elif cb['type'] == 'trade' and cb['traded_price'] > 0:
                        entry['traded_price'] = cb['traded_price']
                        entry['traded_volume'] = cb['traded_volume']
                else:
                    remaining.append(cb)
            self._unmapped_callbacks = remaining

    # =========================================================================
    # Intent mapping
    # =========================================================================

    @staticmethod
    def _map_intent(intent: Optional[OrderIntent]) -> int:
        """Map OrderIntent to xtconstant direction."""
        if intent is None:
            return xtconstant.STOCK_BUY
        mapping = {
            OrderIntent.ENTRY_LONG: xtconstant.STOCK_BUY,
            OrderIntent.EXIT_LONG: xtconstant.STOCK_SELL,
            OrderIntent.ENTRY_SHORT: xtconstant.STOCK_SELL,
            OrderIntent.EXIT_SHORT: xtconstant.STOCK_BUY,
            OrderIntent.FORCED_EXIT: xtconstant.STOCK_SELL,
            OrderIntent.ROLLOVER_CLOSE: xtconstant.STOCK_SELL,
            OrderIntent.ROLLOVER_OPEN: xtconstant.STOCK_BUY,
        }
        return mapping.get(intent, xtconstant.STOCK_BUY)

    # =========================================================================
    # Dashboard
    # =========================================================================

    def _generate_dashboard(self) -> None:
        """Generate per-slot + portfolio aggregate dashboard and save locally."""
        from ..io.kpi_aggregator import generate_portfolio_dashboard, save_portfolio_dashboard

        # Build slot statuses from runtime state
        slot_statuses = {}
        for slot in self.slots:
            if slot.is_errored:
                slot_statuses[slot.slot_id] = 'ERROR'
            else:
                slot_statuses[slot.slot_id] = 'OK'

        # Portfolio equity/peak from runtime
        portfolio_equity = sum(
            s.capital_slot.equity for s in self.slots if s.capital_slot
        )
        portfolio_peak = self.risk_overlay._peak_portfolio_equity if hasattr(self.risk_overlay, '_peak_portfolio_equity') else portfolio_equity

        dashboard = generate_portfolio_dashboard(
            deploy_config=self.config,
            deploy_data_dir=self.deploy_data_dir,
            portfolio_equity=portfolio_equity,
            portfolio_peak=portfolio_peak,
            slot_statuses=slot_statuses,
        )

        out_path = os.path.join(self.portfolio_dir, "dashboard_portfolio.json")
        save_portfolio_dashboard(dashboard, out_path)

    # =========================================================================
    # Health report
    # =========================================================================

    def _save_health_report(self, cycle_start: datetime, results: Dict[str, Any]) -> None:
        """Save cycle_health_report.json."""
        report = {
            'timestamp': cycle_start.isoformat(),
            'duration_seconds': (datetime.now() - cycle_start).total_seconds(),
            'overall_status': results.get('status', 'unknown'),
            'slots': {},
        }

        has_price_failures = False
        for slot in self.slots:
            # Detect fills with unresolved prices
            price_unknown_fills = [
                f for f in slot.todays_processed_fills
                if f.get('error') == 'PRICE_UNKNOWN'
            ]
            if price_unknown_fills:
                has_price_failures = True

            report['slots'][slot.slot_id] = {
                'is_errored': slot.is_errored,
                'error_message': slot.error_message,
                'fills': len(slot.todays_processed_fills),
                'fills_price_unknown': len(price_unknown_fills),
                'equity': slot.capital_slot.equity if slot.capital_slot else 0,
                'drawdown_pct': slot.capital_slot.drawdown_pct if slot.capital_slot else 0,
            }

        if has_price_failures:
            report['overall_status'] = 'WARNING_PRICE_UNKNOWN'
            report['warning'] = (
                'One or more fills had unresolvable prices. VP was NOT updated '
                'for these fills. Manual reconciliation required — check QMT '
                'positions vs strategy state.'
            )

        path = os.path.join(self.portfolio_dir, "cycle_health_report.json")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w') as f:
            json.dump(report, f, indent=2, default=str)

    # =========================================================================
    # Helpers
    # =========================================================================

    def _ensure_trading_calendars(self) -> None:
        """Generate trading calendar for each unique instrument if missing.

        Called before is_trading_day() to ensure the calendar CSV is
        available. Mirrors TradingRunner._ensure_trading_calendar() but
        iterates all unique (market, instrument) pairs from enabled slots.
        """
        from echolon.data.extractors.shfe.api_day_extractor import SHFEApiDayExtractor
        from echolon.config.paths_config import PathsConfig

        market_data_dir = PathsConfig.from_env().market_data_dir

        seen = set()
        for sc in self.config.get_enabled_slots():
            key = (sc.market, sc.instrument)
            if key in seen:
                continue
            seen.add(key)

            calendar_dir = market_data_dir / sc.market / sc.instrument
            calendar_file = calendar_dir / "trading_calendar.csv"
            if calendar_file.exists():
                continue

            self.log.info(f"Trading calendar not found for {sc.instrument} — generating from static source")
            extractor = SHFEApiDayExtractor(market=sc.market, asset=sc.instrument)
            extractor.generate_trading_calendar(
                source_path=self.config.deploy.trading_calendar_path,
                output_dir=str(calendar_dir),
            )

    def _central_wait_if_night_market(self) -> None:
        """
        If today is a night market day, wait until 21:00 CST before firing orders.

        Uses Asia/Shanghai timezone. Coarse sleep (releases GIL) + spin-wait
        for sub-10ms precision at market open.
        """
        first = self.slots[0].slot_config if self.slots else None
        if not first:
            return

        try:
            is_night = is_night_market_open(first.market, first.instrument, self.present_date)
        except Exception:
            is_night = False

        if not is_night:
            # Day-only session — no need to wait
            time.sleep(2)  # Brief settlement wait
            return

        now_shanghai = datetime.now(self.TIMEZONE)
        # Target 1s after session open to avoid the call-auction-to-continuous
        # transition window. Orders in the first ~500ms can be rejected.
        target = now_shanghai.replace(hour=21, minute=0, second=1, microsecond=0)

        # If we're already past 21:00, no wait needed
        if now_shanghai >= target:
            self.log.info("Night market already open, firing immediately")
            return

        remaining = (target - now_shanghai).total_seconds()
        self.log.info(f"Night market wait: {remaining:.0f}s until 21:00 CST")

        # Coarse sleep — releases GIL, immune to C-extension contention
        while True:
            now_shanghai = datetime.now(self.TIMEZONE)
            remaining = (target - now_shanghai).total_seconds()
            if remaining <= 1.0:
                break
            time.sleep(min(remaining - 1.0, 30.0))

        # Spin-wait for sub-10ms precision at market open
        while datetime.now(self.TIMEZONE) < target:
            time.sleep(0.005)

        self.log.info("Night market open — firing orders now")

    def _get_slot_by_id(self, slot_id: str) -> Optional[TradingSlot]:
        for s in self.slots:
            if s.slot_id == slot_id:
                return s
        return None

    def _get_calendar_path(self) -> Optional[str]:
        """Get path to the deploy trading calendar."""
        from ..config.deploy_config import DeployConfig
        return str(
            Path(__file__).parent.parent / "config" / "trading_calendar.csv"
        )

    def _get_schedule_time(self, date: datetime, market: str, instrument: str) -> Tuple[int, int]:
        """Determine schedule time based on night market status."""
        try:
            if is_night_market_open(market, instrument, date):
                return self.config.deploy.night_market_schedule_hour, self.config.deploy.night_market_schedule_minute
            return self.config.deploy.day_only_schedule_hour, self.config.deploy.day_only_schedule_minute
        except Exception:
            return self.config.deploy.night_market_schedule_hour, self.config.deploy.night_market_schedule_minute

    def _find_next_trading_day(self, after_date: datetime, market: str, instrument: str) -> Optional[datetime]:
        """Find next trading day after given date."""
        start = after_date + timedelta(days=1)
        end = after_date + timedelta(days=30)
        trading_dates = get_trading_dates(
            market, instrument,
            start_date=start.strftime("%Y-%m-%d"),
            end_date=end.strftime("%Y-%m-%d"),
        )
        if not trading_dates:
            return None
        first = trading_dates[0]
        if hasattr(first, 'to_pydatetime'):
            first = first.to_pydatetime()
        return first

    def _reschedule_next_job(self) -> None:
        """Schedule next daily job."""
        if not self.scheduler:
            return
        first = self.slots[0].slot_config if self.slots else None
        if not first:
            return

        try:
            next_day = self._find_next_trading_day(datetime.now(), first.market, first.instrument)
            if next_day is None:
                self.log.error("No future trading days found")
                return

            hour, minute = self._get_schedule_time(next_day, first.market, first.instrument)
            run_date = self.TIMEZONE.localize(
                next_day.replace(hour=hour, minute=minute, second=0, microsecond=0)
            )

            for job in self.scheduler.get_jobs():
                if job.name == "PortfolioDailyJob":
                    job.remove()

            self.scheduler.add_job(
                self._market_open_job,
                trigger=DateTrigger(run_date=run_date),
                name="PortfolioDailyJob",
                misfire_grace_time=self.config.deploy.misfire_grace_time,
            )
            self.log.info(f"Rescheduled: {next_day.strftime('%Y-%m-%d')} at {hour:02d}:{minute:02d}")
        except Exception as e:
            self.log.error(f"Rescheduling failed: {e}")

    def _signal_handler(self, signum, frame) -> None:
        """Handle SIGINT/SIGTERM."""
        self.log.info(f"Received signal {signum} — shutting down")
        self.stop()
