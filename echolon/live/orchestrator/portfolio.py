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
    from ..platforms.miniqmt.order_router import (
        OrderRouter, RouterCallbacks, OrderHandle, OrderState,
    )
except ImportError:
    MiniQMTClient = None
    OrderRouter = None
    RouterCallbacks = None
    OrderHandle = None
    OrderState = None

from ..config.qmt_constants import QMT_STATUS_MAP

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
        # OrderRouter — drives all order lifecycle (Phase 2+).
        self.order_router: Optional["OrderRouter"] = None

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

        # OrderRouter-driven state. Replaces the legacy _order_events /
        # _seq_to_order_id / _unmapped_callbacks plumbing. All order
        # lifecycle is now owned by OrderRouter; the runner observes via
        # RouterCallbacks and queues bookkeeping records here for the
        # main thread to drain in _process_fills.
        self._callback_lock = threading.Lock()
        # Per-slot list of (Order, OrderHandle) — handle holds the chain.
        self._slot_handle_map: Dict[str, List[Tuple[Order, "OrderHandle"]]] = {}
        # Terminal-event records produced by router callbacks (watchdog
        # thread); _process_fills drains and books these on the main
        # thread to avoid concurrent VP mutations.
        self._slot_terminal_records: Dict[str, List[Dict[str, Any]]] = defaultdict(list)

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
        # Windows-only — NSSM's stop sequence escalates from Ctrl+C
        # (SIGINT) to Ctrl+Break (SIGBREAK) after a 1.5s grace period.
        # Without this handler the second event would terminate the
        # process abruptly, skipping our cleanup.
        original_sigbreak = None
        if hasattr(signal, "SIGBREAK"):
            original_sigbreak = signal.getsignal(signal.SIGBREAK)
            signal.signal(signal.SIGBREAK, self._signal_handler)

        try:
            # Disable Windows CMD QuickEdit Mode — accidental clicks must
            # not pause the trader by blocking stdout. No-op on non-Windows.
            from echolon._internal.console_utils import disable_quickedit_mode
            disable_quickedit_mode()

            self._connect_client()
            self.risk_overlay.load(active_slot_ids=[s.slot_id for s in self.slots])
            self._schedule_daily_trading()

            while self.running and not self.shutdown_event.is_set():
                self.shutdown_event.wait(timeout=60)
                # Heartbeat: write a timestamp file every minute so the
                # operator can verify liveness via `type scheduler_heartbeat.txt`
                # without depending on console output (which can block).
                self._write_scheduler_heartbeat()
        except Exception as e:
            self.log.error(f"Fatal error: {e}\n{traceback.format_exc()}")
        finally:
            signal.signal(signal.SIGINT, original_sigint)
            signal.signal(signal.SIGTERM, original_sigterm)
            if original_sigbreak is not None:
                signal.signal(signal.SIGBREAK, original_sigbreak)
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

        if self.order_router:
            try:
                self.order_router.shutdown()
            except Exception:
                pass
            self.order_router = None

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
        """Create and connect shared MiniQMTClient + OrderRouter."""
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
            # Construct OrderRouter — it registers its own callbacks on
            # the client. The router fans out to our handlers below.
            callbacks = RouterCallbacks(
                on_filled=self._on_router_filled,
                on_partial=self._on_router_partial,
                on_abandoned=self._on_router_abandoned,
                on_rejected=self._on_router_rejected,
                on_circuit_tripped=self._on_router_circuit_tripped,
            )
            self.order_router = OrderRouter(
                client=self.client,
                callbacks=callbacks,
                state_dir=Path(self.portfolio_dir),
            )
            self.order_router.start()
            self.log.info("OrderRouter started")
            if self.order_router.is_tripped:
                self.log.critical(
                    f"OrderRouter started TRIPPED from persisted state: "
                    f"{self.order_router.tripped_reason}. Run "
                    f"`goingmerry order-router-reset` after investigating."
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
            id="portfolio_daily_job",
            name="PortfolioDailyJob",
            replace_existing=True,
            misfire_grace_time=self.config.deploy.misfire_grace_time,
            coalesce=True,
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
        self._slot_handle_map.clear()
        self._slot_terminal_records.clear()
        # Reset OrderRouter per-cycle health metrics so that
        # abandon/reject rates aren't diluted by all-time totals.
        if self.order_router is not None:
            self.order_router.reset_cycle_metrics()
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
                intent_str = order.intent.value if order.intent else "ENTRY_LONG"

                # Phase 2: route through OrderRouter. The router runs the
                # state machine, watchdog cancel-and-resubmit, splitter,
                # BandGuard, and circuit breaker. We only see terminal
                # outcomes via the callbacks wired in _connect_client.
                if self.order_router is None:
                    order.status = OrderStatus.REJECTED
                    self.log.error(f"[{slot_id}] No OrderRouter — cannot submit")
                    continue

                # If this is an EXIT-class order, set pending_exit_intent
                # BEFORE the first attempt — Amendment B. This way even
                # an immediate-rejection abandons can be recovered next cycle.
                if intent_str in ("EXIT_LONG", "EXIT_SHORT", "ROLLOVER_CLOSE", "FORCED_EXIT"):
                    self._set_pending_exit_intent(
                        slot=slot, intent=intent_str,
                        original_size=int(order.size),
                    )

                # If the caller specified an explicit price (e.g. the
                # kill-at-band-edge recovery in TradingSlot._resume_pending_exit),
                # honor it as a LIMIT — bypass router's aggressive pricing.
                # Strategies that want MARKET-equivalent behaviour leave
                # order.price=None.
                if order.price is not None and float(order.price) > 0:
                    handle = self.order_router.submit_order(
                        intent=intent_str,
                        symbol=order.symbol,
                        volume=int(order.size),
                        slot_id=slot_id,
                        intended_price=float(order.price),
                        force_price=float(order.price),
                    )
                else:
                    handle = self.order_router.submit_order(
                        intent=intent_str,
                        symbol=order.symbol,
                        volume=int(order.size),
                        slot_id=slot_id,
                        intended_price=order.price,
                    )

                if handle.state == OrderState.SUBMITTED:
                    order.status = OrderStatus.SUBMITTED
                    order.metadata['qmt_seq_id'] = handle.seq_id
                    self._slot_handle_map.setdefault(slot_id, []).append((order, handle))
                    self.log.info(
                        f"[{slot_id}] Routed: {intent_str} "
                        f"{order.size}@{order.price} -> seq={handle.seq_id} "
                        f"submitted_price={handle.submitted_price:.2f}"
                    )
                else:
                    # Immediate rejection (e.g. submit_order_async returned no seq_id).
                    order.status = OrderStatus.REJECTED
                    self.log.error(
                        f"[{slot_id}] OrderRouter rejected immediately: {intent_str} "
                        f"state={handle.state.value} msg={handle.last_status_msg}"
                    )

            except Exception as e:
                order.status = OrderStatus.REJECTED
                self.log.error(f"[{slot_id}] Order fire error: {e}\n{traceback.format_exc()}")

    # =========================================================================
    # Phase 3: Process fills
    # =========================================================================

    def _process_fills(self, timeout: float = 600.0) -> None:
        """Wait for OrderRouter chain resolution per submitted intent,
        then book all terminal events on the main thread.

        Router callbacks fire on the watchdog thread and append to
        self._slot_terminal_records. We block per intent's chain_resolved
        event until the full retry+split chain is done, then drain the
        recorded terminal events for that slot's intents.
        """
        # Phase A — block until every submitted intent's chain has fully resolved.
        for slot_id, order_list in self._slot_handle_map.items():
            slot = self._get_slot_by_id(slot_id)
            if slot is None or slot.is_errored:
                continue
            for order, handle in order_list:
                if handle.chain_resolved is None:
                    continue
                self.log.info(
                    f"[{slot_id}] Waiting for chain seq={handle.seq_id} "
                    f"({order.intent.value if order.intent else '?'} "
                    f"{order.size}@{order.price})..."
                )
                resolved = handle.chain_resolved.wait(timeout=timeout)
                if not resolved:
                    self.log.warning(
                        f"[{slot_id}] Chain timeout seq={handle.seq_id} "
                        f"after {timeout}s — booking partial state"
                    )

        # Phase B — book the recorded terminal events on the main thread.
        for slot_id, order_list in self._slot_handle_map.items():
            slot = self._get_slot_by_id(slot_id)
            if slot is None or slot.is_errored:
                continue

            with self._callback_lock:
                records = list(self._slot_terminal_records.get(slot_id, []))

            for record in records:
                kind = record["kind"]
                handle = record["handle"]
                # Find the originating Order — match by chain root seq_id.
                chain_root = handle.original_handle_id or handle.seq_id
                order = self._find_order_for_chain(order_list, chain_root)
                if order is None:
                    # Most commonly: an immediately-rejected handle whose
                    # fake-negative seq_id never made it into the slot's
                    # handle_map. The on_rejected callback already logged
                    # the rejection at submit time; nothing else to book.
                    self.log.debug(
                        f"[{slot_id}] Skipping record kind={kind} "
                        f"seq={handle.seq_id}: no matching order in handle_map"
                    )
                    continue

                # Coerce kind → status code for legacy bookkeeping branches.
                if kind == "filled":
                    status = 56
                elif kind == "partial":
                    status = 55
                elif kind == "rejected":
                    status = 57
                else:                       # abandoned (treated like cancel)
                    status = 54

                traded_price = handle.filled_avg_price
                traded_volume = handle.filled_volume
                real_id = handle.qmt_order_id or handle.seq_id
                exec_status = QMT_STATUS_MAP.get(status, f'UNKNOWN_{status}')

                self.log.info(
                    f"[{slot_id}] Terminal: kind={kind} "
                    f"status={exec_status} price={traded_price} "
                    f"volume={traded_volume} seq={handle.seq_id} "
                    f"reason={record.get('reason', '')}"
                )

                # The bookkeeping branches below mirror the legacy code
                # (FILLED / CANCELED / REJECTED); they apply VP updates,
                # write per-slot CSVs, and update strategy loggers.

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

                elif status in (53, 54):  # CANCELED / ABANDONED
                    order.status = OrderStatus.CANCELLED
                    msg = handle.last_status_msg or record.get('reason', '')
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
                    msg = handle.last_status_msg or record.get('reason', '')
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

        # Phase C — chain-aware pending_exit_intent reconciliation
        # (Amendment B). Process AFTER per-record bookkeeping so split chains
        # are accounted in aggregate. For each EXIT-class submitted intent,
        # sum filled_volume across the entire chain (parent + retries +
        # split chunks) and decide whether to clear or update the intent.
        for slot_id, order_list in self._slot_handle_map.items():
            slot = self._get_slot_by_id(slot_id)
            if slot is None or slot.is_errored:
                continue
            with self._callback_lock:
                records = list(self._slot_terminal_records.get(slot_id, []))
            for order, parent_handle in order_list:
                intent_str = order.intent.value if order.intent else ""
                if intent_str not in (
                    "EXIT_LONG", "EXIT_SHORT", "ROLLOVER_CLOSE", "FORCED_EXIT"
                ):
                    continue
                chain_root = parent_handle.seq_id
                chain_records = [
                    r for r in records
                    if (r["handle"].original_handle_id or r["handle"].seq_id)
                    == chain_root
                ]
                # Sum filled across all chain handles. Each handle's
                # filled_volume is the deduped sum of its trade callbacks.
                # Per-handle filled is independent so summing is safe.
                seen_handles: Dict[int, int] = {}
                for r in chain_records:
                    seen_handles[r["handle"].seq_id] = r["handle"].filled_volume
                total_filled = sum(seen_handles.values())
                original = int(order.size)
                remaining = max(0, original - total_filled)
                if remaining <= 0:
                    self._clear_pending_exit_intent(slot)
                else:
                    self._update_pending_exit_remaining(slot, remaining)

    def _resolve_fill_price(self, order_id: int, slot_id: str) -> float:
        """Attempt to resolve a fill price when the trade callback didn't
        provide one. Fallback queries QMT trade history.
        """
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
    # OrderRouter callbacks (from watchdog thread — append-only here)
    # =========================================================================

    def _on_router_filled(self, handle: "OrderHandle") -> None:
        """Router-side notification that a handle reached TERMINAL_FILLED."""
        with self._callback_lock:
            self._slot_terminal_records[handle.slot_id].append({
                "kind": "filled", "handle": handle,
            })

    def _on_router_partial(self, handle: "OrderHandle") -> None:
        """A handle's chain has accumulated some fill but isn't complete yet."""
        with self._callback_lock:
            self._slot_terminal_records[handle.slot_id].append({
                "kind": "partial", "handle": handle,
            })

    def _on_router_abandoned(
        self, handle: "OrderHandle", remaining: int, reason: str,
    ) -> None:
        """Chain exhausted retries / hit slippage cap / etc."""
        with self._callback_lock:
            self._slot_terminal_records[handle.slot_id].append({
                "kind": "abandoned", "handle": handle,
                "remaining": remaining, "reason": reason,
            })

    def _on_router_rejected(self, handle: "OrderHandle") -> None:
        """Broker rejected the order."""
        with self._callback_lock:
            self._slot_terminal_records[handle.slot_id].append({
                "kind": "rejected", "handle": handle,
            })

    def _on_router_circuit_tripped(self, reason: str) -> None:
        """Circuit broke — log critical alert. The router itself refuses
        further submits via OrderRouterTripped; nothing for us to gate."""
        self.log.critical(
            f"OrderRouter circuit TRIPPED: {reason}. "
            f"Cycle continues to drain in-flight orders. "
            f"Run `goingmerry order-router-reset` after investigating."
        )

    # ---- Pending-exit-intent helpers (Amendment B) ------------------------

    def _set_pending_exit_intent(
        self, slot: TradingSlot, intent: str, original_size: int,
    ) -> None:
        """Record an EXIT-class submission so the next cycle can recover."""
        if not slot._state_path:
            return
        try:
            from echolon.strategy.state_manager import StateManager, PendingExitIntent
            sm = StateManager(state_path=slot._state_path)
            sm.load_state()
            now = datetime.now().isoformat()
            existing = sm.get_pending_exit_intent()
            if existing is not None and existing.intent == intent:
                # Already pending from a prior cycle — bump and re-save.
                existing.last_attempt_time = now
                sm.set_pending_exit_intent(existing)
            else:
                sm.set_pending_exit_intent(PendingExitIntent(
                    intent=intent,
                    original_size=int(original_size),
                    remaining_size=int(original_size),
                    attempts_so_far=0,
                    original_decision_time=now,
                    last_attempt_time=now,
                    cycles_pending=1,
                ))
            sm.save_state()
        except Exception as exc:
            self.log.error(f"[{slot.slot_id}] set_pending_exit_intent failed: {exc}")

    def _clear_pending_exit_intent(self, slot: TradingSlot) -> None:
        if not slot._state_path:
            return
        try:
            from echolon.strategy.state_manager import StateManager
            sm = StateManager(state_path=slot._state_path)
            sm.load_state()
            sm.clear_pending_exit_intent()
            sm.save_state()
        except Exception as exc:
            self.log.error(f"[{slot.slot_id}] clear_pending_exit_intent failed: {exc}")
        # Also remove operator alert row for this slot, if any.
        try:
            self._remove_pending_exit_alert(slot.slot_id)
        except Exception as exc:
            self.log.error(f"[{slot.slot_id}] remove_pending_exit_alert failed: {exc}")

    def _remove_pending_exit_alert(self, slot_id: str) -> None:
        """Remove a slot's entry from pending_exit_alerts.json."""
        alert_path = Path(self.portfolio_dir) / "pending_exit_alerts.json"
        if not alert_path.exists():
            return
        try:
            with open(alert_path, "r") as f:
                existing = json.load(f)
            if not isinstance(existing, list):
                return
        except (OSError, json.JSONDecodeError):
            return
        new = [a for a in existing if a.get("slot_id") != slot_id]
        if len(new) == len(existing):
            return
        tmp = alert_path.with_suffix(".json.tmp")
        with open(tmp, "w") as f:
            json.dump(new, f, indent=2)
        os.replace(tmp, alert_path)

    def _update_pending_exit_remaining(
        self, slot: TradingSlot, remaining: int,
    ) -> None:
        if not slot._state_path:
            return
        try:
            from echolon.strategy.state_manager import StateManager
            sm = StateManager(state_path=slot._state_path)
            sm.load_state()
            pending = sm.get_pending_exit_intent()
            if pending is None:
                return
            pending.remaining_size = max(0, int(remaining))
            pending.attempts_so_far += 1
            pending.last_attempt_time = datetime.now().isoformat()
            sm.set_pending_exit_intent(pending)
            sm.save_state()
        except Exception as exc:
            self.log.error(f"[{slot.slot_id}] update_pending_exit_remaining failed: {exc}")

    # ---- Lookup helpers ---------------------------------------------------

    def _find_order_for_chain(
        self,
        order_list: List[Tuple[Order, "OrderHandle"]],
        chain_root_seq: int,
    ) -> Optional[Order]:
        """Locate the originating Order for a handle in a retry/split chain.

        Returns ``None`` when no order in the slot's tracked list matches
        the chain root (e.g. an immediately-rejected handle whose fake
        seq_id never made it into ``_slot_handle_map``). Callers MUST
        handle ``None`` and skip the record — using a wrong order would
        write the rejected status to a different order's CSV and corrupt
        the audit trail.
        """
        for order, parent_handle in order_list:
            if parent_handle.seq_id == chain_root_seq:
                return order
        return None

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
        available. Iterates all unique (market, instrument) pairs from
        enabled slots and asks the SHFE day extractor to materialize each.
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
        """Get path to the deploy trading calendar.

        The CSV is supplied by the operator via the JSON config
        (``deploy.trading_calendar_path``), not bundled with echolon.
        """
        path = self.config.deploy.trading_calendar_path
        if not path:
            raise FileNotFoundError(
                "deploy.trading_calendar_path is not set in PortfolioDeployConfig; "
                "supply it via the JSON config (e.g. "
                "goingmerry/session/portfolio_deploy_config.json)."
            )
        return path

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
                id="portfolio_daily_job",
                name="PortfolioDailyJob",
                replace_existing=True,
                misfire_grace_time=self.config.deploy.misfire_grace_time,
                coalesce=True,
            )
            self.log.info(f"Rescheduled: {next_day.strftime('%Y-%m-%d')} at {hour:02d}:{minute:02d}")
        except Exception as e:
            self.log.error(f"Rescheduling failed: {e}")

    def _signal_handler(self, signum, frame) -> None:
        """Handle SIGINT/SIGTERM."""
        self.log.info(f"Received signal {signum} — shutting down")
        self.stop()

    def _write_scheduler_heartbeat(self) -> None:
        """Write a heartbeat file with current time + next-job time.

        The operator monitors this file (`type scheduler_heartbeat.txt`)
        to verify the runner is still ticking — without depending on
        console output, which can block under Windows CMD QuickEdit
        Mode. Atomic write via temp+rename so partial reads can't see
        a corrupted file.
        """
        if not self.scheduler:
            return
        try:
            jobs = self.scheduler.get_jobs() if self.scheduler else []
            next_job_run = None
            for j in jobs:
                if j.name == "PortfolioDailyJob" and j.next_run_time is not None:
                    next_job_run = j.next_run_time.isoformat()
                    break

            heartbeat_path = Path(self.portfolio_dir) / "scheduler_heartbeat.txt"
            heartbeat_path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = heartbeat_path.with_suffix(".txt.tmp")
            content = (
                f"now={datetime.now(self.TIMEZONE).isoformat()}\n"
                f"next_daily_job={next_job_run or 'NONE'}\n"
                f"running={self.running}\n"
                f"slots={len(self.slots)}\n"
                f"order_router_tripped="
                f"{self.order_router.is_tripped if self.order_router else 'no_router'}\n"
            )
            tmp_path.write_text(content, encoding="utf-8")
            os.replace(tmp_path, heartbeat_path)
        except Exception:
            # Heartbeat is best-effort; never raise from here.
            pass
