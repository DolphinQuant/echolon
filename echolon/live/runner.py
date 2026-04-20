"""
Trading Runner
==============

High-level orchestrator for live trading sessions.

Replaces QTS_deploy's main_trading.py + miniqmt/run_trading.py with a clean,
modular implementation that uses the new deploy infrastructure.

Responsibilities:
- Initialize MiniQMTClient, QMTEngine, and strategy
- Run data pipeline (download, indicators, strategy extraction)
- Schedule daily trading cycles via APScheduler
- Handle contract expiry (via ForcedExitStrategyHook)
- Persist state across sessions via StateManager
- Graceful shutdown with signal handling

Trading cycle flow:
1. Refresh portfolio data from QMT
2. Execute strategy.on_bar() (hooks handle forced exit automatically)
3. Save state via StateManager
4. Finalize strategy logger (flush CSV)

Scheduling:
- Night market open: Run at config.night_market_schedule_hour:minute
- Day only: Run at config.day_only_schedule_hour:minute
- Dynamic rescheduling after each cycle based on next day's night market

Usage:
    runner = TradingRunner(config=deploy_config, ctx=trading_context)
    runner.run()  # Blocking, runs until stopped

    # Or single cycle (for testing)
    results = runner.run_single_cycle()
"""

import json
import os
import signal
import threading
import time
import traceback
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

import pytz
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.date import DateTrigger

from echolon.config.markets.core.context import TradingContext
from .config.deploy_config import DeployConfig
from .config.logging_config import get_deploy_logger, init_logging, shutdown_logging
try:
    from .platforms.miniqmt.qmt_client import MiniQMTClient
except ImportError:
    MiniQMTClient = None  # Available only on QMT-enabled machines

from echolon.data.loaders.contract_loader import get_main_contract
from echolon.data.loaders.calendar_loader import (
    get_trading_dates,
    is_trading_day,
    is_night_market_open,
)
from echolon.backtest.engine_factory import EngineFactory
from echolon.strategy.hooks.forced_exit_strategy_hook import ForcedExitStrategyHook
from .data_logger import save_trading_data_snapshot, save_trade_execution
from echolon.strategy.interfaces import OrderStatus
from echolon.config.settings import MARKET_DATA_DIR
from echolon.data.live_data import run_live_data_update
from echolon.indicators.run import run_indicator_calculation

class TradingRunner:
    """
    Main orchestrator for live trading sessions.

    Ties together the MiniQMT client, QMT engine, data pipeline,
    platform-agnostic strategy, state management, and scheduling
    into a single coherent trading loop.

    Args:
        config: Deployment configuration with account, paths, and scheduling.
        ctx: TradingContext with market, instrument, and frequency config.
    """

    # Timezone for all scheduling
    TIMEZONE = pytz.timezone("Asia/Shanghai")

    def __init__(self, config: DeployConfig, ctx: TradingContext):
        self.config = config
        self.ctx = ctx
        self.engine = None
        self.strategy = None
        self.client = None
        self.state_path = None
        self.scheduler = None
        self.running = False
        self.shutdown_event = threading.Event()
        self.present_date = datetime.now()
        self.main_contract = None

        # Trading data tracking for dashboard logging
        self._prev_total_pnl = 0.0
        self._prev_position_size = 0
        self._prev_avg_price = 0.0

        # Callback-based order tracking: qmt_order_id -> dict
        # Written by _on_order_update (callback thread), read by _wait_and_log_executions
        self._order_events = {}  # {qmt_id: {'event': Event, 'status': int, ...}}

        # Initialize logging
        logs_dir = os.path.join(config.trading_data_dir, "logs")
        init_logging(logs_dir)
        self.logger = get_deploy_logger("trading_runner")

    # =========================================================================
    # Public API
    # =========================================================================

    def run(self):
        """
        Main entry point: schedule and run daily trading jobs.

        Blocks until shutdown_event is set (via stop() or signal handler).
        Registers SIGINT and SIGTERM handlers for graceful shutdown.
        """
        self.logger.info("=" * 70)
        self.logger.info("STARTING TRADING RUNNER")
        self.logger.info(f"Market: {self.ctx.market_code}, "
                         f"Instrument: {self.ctx.instrument_name}, "
                         f"Account: {'TEST' if self.config.use_test_account else 'LIVE'}")
        self.logger.info("=" * 70)

        self.running = True

        # Register signal handlers
        original_sigint = signal.getsignal(signal.SIGINT)
        original_sigterm = signal.getsignal(signal.SIGTERM)
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

        try:
            # Schedule daily trading job
            self._schedule_daily_trading()

            # Block until shutdown
            while self.running and not self.shutdown_event.is_set():
                # Wait with timeout so signals can be processed
                self.shutdown_event.wait(timeout=60)

        except Exception as e:
            self.logger.error(f"Fatal error in trading runner: {e}")
            self.logger.error(traceback.format_exc())
        finally:
            # Restore original signal handlers
            signal.signal(signal.SIGINT, original_sigint)
            signal.signal(signal.SIGTERM, original_sigterm)
            self.stop()

    def run_single_cycle(self) -> Dict[str, Any]:
        """
        Execute a single trading cycle for testing.

        Performs full initialization, runs one bar, and returns results.
        Does NOT start the scheduler.

        Returns:
            Dictionary with cycle results including status and metrics.
        """
        self.logger.info("Running single trading cycle (test mode)")
        self.running = True

        try:
            self._initialize()
            return self._execute_trading_cycle()
        except Exception as e:
            self.logger.error(f"Single cycle failed: {e}")
            self.logger.error(traceback.format_exc())
            return {
                "status": "error",
                "error": str(e),
                "timestamp": datetime.now().isoformat(),
            }
        finally:
            self.running = False

    def stop(self):
        """
        Graceful shutdown of all components.

        Safe to call multiple times.
        """
        if not self.running and self.shutdown_event.is_set():
            return  # Already stopped

        self.logger.info("Initiating graceful shutdown...")
        self.running = False
        self.shutdown_event.set()

        # Finalize strategy logging
        if self.strategy and hasattr(self.strategy, "strategy_logger"):
            try:
                if self.strategy.strategy_logger:
                    log_file = self.strategy.strategy_logger.finalize_logging()
                    if log_file:
                        self.logger.info(f"Strategy log saved: {log_file}")
            except Exception as e:
                self.logger.error(f"Error finalizing strategy logger: {e}")

        # Disconnect QMT client
        if self.client:
            try:
                self.client.disconnect()
                self.logger.info("QMT client disconnected")
            except Exception as e:
                self.logger.error(f"Error disconnecting client: {e}")
            self.client = None

        # Shutdown scheduler
        if self.scheduler:
            try:
                self.scheduler.shutdown(wait=False)
                self.logger.info("Scheduler shut down")
            except Exception as e:
                self.logger.error(f"Error shutting down scheduler: {e}")
            self.scheduler = None

        # Shutdown logging
        shutdown_logging()
        self.engine = None
        self.strategy = None

    # =========================================================================
    # Initialization
    # =========================================================================

    def _initialize(self):
        """
        Full initialization sequence.

        Steps:
        1. Create and connect MiniQMTClient
        2. Run data pipeline (download + indicators)
        3. Create QMTEngine via EngineFactory
        4. Load indicators into engine
        5. Set current bar to today
        6. Load trial params and create strategy
        7. Add ForcedExitStrategyHook
        8. Start strategy and restore state
        """
        self.present_date = datetime.now()
        self.logger.info(f"Initializing for date={self.present_date.strftime('%Y-%m-%d')}")

        # Step 1: Create and connect MiniQMT client
        self._connect_client()

        # Step 2: Run data pipeline (creates main_contract.csv + indicators)
        self._prepare_data()

        # Step 2.5: Resolve main contract (requires main_contract.csv from data pipeline)
        self.main_contract = get_main_contract(self.present_date)
        self.logger.info(f"Main contract: {self.main_contract}")

        # Step 3: Create QMT engine
        calendar_path = self._get_calendar_path()
        self.engine = EngineFactory.create_deploy_engine(
            ctx=self.ctx,
            calendar_path=calendar_path,
            client=self.client,
            platform="miniqmt",
        )
        self.logger.info("QMTEngine created via EngineFactory")

        # Set the specific contract code for order placement
        if self.main_contract:
            self.engine.set_trading_contract(self.main_contract)
            self.logger.info(f"Trading contract set to {self.main_contract}")

        # Step 4: Load indicators
        indicators_path = self._get_indicators_path()
        self.engine.load_data(indicators_path)
        self.logger.info(f"Indicators loaded from {indicators_path}")

        # Step 5: Set current bar to today
        market_data = self.engine.get_market_data()
        today_dt = datetime.combine(self.present_date.date(), datetime.min.time())
        market_data.set_current_bar(today_dt)
        self.logger.info(f"Current bar set to {today_dt.date()}")

        # Step 6: Load trial params and create strategy
        strategy_params = self._load_and_map_trial_params()
        self._create_strategy(strategy_params)

        # Step 7: Add ForcedExitStrategyHook
        hook = ForcedExitStrategyHook(
            market_adapter=self.engine.get_market_adapter()
        )
        self.strategy.add_hook(hook)
        self.logger.info("ForcedExitStrategyHook added to strategy")

        # Step 8: Start strategy and restore state
        self.strategy.on_start()
        self.logger.info("Strategy started (on_start called)")

        self.state_path = os.path.join(self.config.strategy_data_dir, "strategy_state.json")
        self.strategy.restore_state(self.state_path)
        self.logger.info("Initialization complete")

    def _connect_client(self):
        """Create MiniQMTClient and connect to QMT."""
        account = self.config.active_account
        self.logger.info(f"Connecting to QMT: path={account.qmt_path}, "
                         f"account={account.account_id}, "
                         f"type={account.account_type}")

        self.client = MiniQMTClient(
            config=account,
            market=self.ctx.market_code,
            asset=self.ctx.instrument_name,
        )

        connected = self.client.connect()
        if connected:
            self.logger.info("QMT connection established")
            # Log account info
            try:
                account_info = self.client.get_account_info()
                if account_info:
                    self.logger.info(
                        f"Account info: cash={account_info.get('available_cash', 'N/A')}, "
                        f"total={account_info.get('total_asset', 'N/A')}"
                    )
            except Exception as e:
                self.logger.warning(f"Could not retrieve account info: {e}")

            # Set up callbacks
            self.client.set_callbacks(
                order_callback=self._on_order_update,
                trade_callback=self._on_trade_update,
                market_data_callback=self._on_market_data_update,
            )
        else:
            self.logger.warning(
                "QMT connection failed (may be outside trading hours). "
                "Continuing with limited functionality."
            )

    def _prepare_data(self):
        """Run the data pipeline to download and process market data.

        Uses the centralized data pipeline with source="qmt" for live
        MiniQMT data extraction. Splitting is skipped because the live
        extractor saves per-contract CSVs during download.
        """

        self.logger.info("Running data pipeline...")

        success = run_live_data_update(
            ctx=self.ctx,
            client=self.client,
            present_date=self.present_date,
            trading_calendar_path=self.config.trading_calendar_path,
            skip_calendar=True,  # Calendar already ensured by _ensure_trading_calendar()
        )

        if success:
            self.logger.info("Data pipeline completed successfully")
        else:
            self.logger.error("Data pipeline failed -- proceeding with existing data")
        
        result = run_indicator_calculation(
                ctx=self.ctx,
                selected_only=True,
                use_parallel=True,
                mode='deploy',
                optimize_regime=False,  # Use cached regime params if available
            )

    def _create_strategy(self, strategy_params: Dict[str, Any]):
        """Import and instantiate the platform-agnostic strategy."""
        from pathlib import Path
        from echolon.strategy.loader import StrategyLoader
        from echolon.config.settings import PLATFORM_AGNOSTIC_DIR

        loader = StrategyLoader(Path(PLATFORM_AGNOSTIC_DIR))
        strategy_main = loader.load_function("strategy", "strategy_main")

        self.strategy = strategy_main(
            trading_engine=self.engine,
            strategy_dir=PLATFORM_AGNOSTIC_DIR,
            **strategy_params,
        )
        self.logger.info("Strategy instance created")

    # =========================================================================
    # Trading Cycle
    # =========================================================================

    def _execute_trading_cycle(self) -> Dict[str, Any]:
        """
        Execute a single bar of the trading strategy.

        Steps:
        1. Refresh portfolio data from QMT
        2. Execute strategy.on_bar() (hook checks expiry + processes signal)
        3. Save state
        4. Finalize strategy logger
        5. Return cycle results

        Returns:
            Dictionary with cycle results.
        """
        cycle_start = datetime.now()
        self.logger.info("-" * 50)
        self.logger.info(f"EXECUTING TRADING CYCLE at {cycle_start.strftime('%H:%M:%S')}")

        # Step 1: Refresh portfolio from QMT
        try:
            self.engine.refresh()
            self.logger.info("Portfolio data refreshed from QMT")
        except Exception as e:
            self.logger.error(f"Portfolio refresh failed: {e}")

        # Step 2: Execute strategy bar
        # ForcedExitStrategyHook.on_bar_start() checks contract expiry
        # and processes forced exit before strategy logic runs.
        try:
            self.strategy.on_bar()
            self.logger.info("Strategy on_bar() executed")
        except Exception as e:
            self.logger.error(f"Strategy on_bar() failed: {e}")
            self.logger.error(traceback.format_exc())
            return {
                "status": "error",
                "error": str(e),
                "timestamp": cycle_start.isoformat(),
            }

        # Step 3: Save state
        try:
            self.strategy.save_state(self.state_path)
            self.logger.info("Strategy state saved")
        except Exception as e:
            self.logger.error(f"State save failed: {e}")

        # Step 3.5: Capture current_bar_data BEFORE finalize clears it
        logger_bar = {}
        if (
            self.strategy
            and hasattr(self.strategy, "strategy_logger")
            and self.strategy.strategy_logger
            and hasattr(self.strategy.strategy_logger, "current_bar_data")
        ):
            logger_bar = dict(self.strategy.strategy_logger.current_bar_data or {})

        # Step 3.6: Wait for callback results & log trade executions
        self._wait_and_log_executions(logger_bar)

        # Step 4: Finalize strategy logger
        log_file = None
        if self.strategy and hasattr(self.strategy, "strategy_logger"):
            try:
                if self.strategy.strategy_logger:
                    log_file = self.strategy.strategy_logger.finalize_logging()
                    if log_file:
                        self.logger.info(f"Strategy log flushed: {log_file}")
            except Exception as e:
                self.logger.error(f"Strategy log finalization failed: {e}")

        # Step 5: Collect results
        cycle_end = datetime.now()
        duration = (cycle_end - cycle_start).total_seconds()

        results = {
            "status": "success",
            "timestamp": cycle_start.isoformat(),
            "duration_seconds": duration,
            "main_contract": self.main_contract,
            "log_file": log_file,
        }

        # Add portfolio snapshot
        try:
            portfolio = self.engine.get_portfolio()
            position = portfolio.get_position()
            results["portfolio"] = {
                "equity": portfolio.get_total_value(),
                "cash": portfolio.get_cash(),
                "has_position": position is not None and position.size > 0,
                "position_size": position.size if position else 0,
                "position_side": position.direction if position else "FLAT",
            }
        except Exception as e:
            self.logger.warning(f"Could not snapshot portfolio: {e}")

        # Step 6: Save trading data snapshot for dashboard
        try:
            md = self.engine.get_market_data()
            portfolio = self.engine.get_portfolio()
            position = portfolio.get_position()

            # Build last_trade_action from captured logger_bar
            last_trade_action = None
            order_action = logger_bar.get('order_action')
            if order_action:
                last_trade_action = {
                    'action': order_action,
                    'price': logger_bar.get('execution_price', 0.0),
                    'size': logger_bar.get('order_size', 0),
                    'timestamp': logger_bar.get('datetime'),
                }

            save_trading_data_snapshot(
                trading_data_dir=self.config.trading_data_dir,
                market_data={
                    'current_price': md.get_current_price(),
                    'daily_open': md.get_open(),
                    'daily_high': md.get_high(),
                    'daily_low': md.get_low(),
                    'volume': md.get_volume(),
                },
                signal_data={
                    'signal_type': logger_bar.get('entry_signal'),
                    'signal_strength': logger_bar.get('entry_strength', 0.0),
                    'signal_confidence': logger_bar.get('entry_strength', 0.0),
                    'signal_reason': logger_bar.get('entry_reason'),
                },
                position_data={
                    'current_position_size': position.size if position else 0,
                    'current_position_avg_price': position.avg_price if position else None,
                    'unrealized_pnl': position.unrealized_pnl if position else 0.0,
                },
                account_data={
                    'available_cash': portfolio.get_cash(),
                    'total_account_value': portfolio.get_total_value(),
                },
                performance_data={
                    'daily_pnl': self.strategy.total_pnl - self._prev_total_pnl,
                    'total_pnl': self.strategy.total_pnl,
                    'win_rate': (self.strategy.win_count / max(self.strategy.trade_count, 1)) * 100,
                    'trade_count': self.strategy.trade_count,
                },
                symbol=self.ctx.instrument_name,
                last_trade_action=last_trade_action,
            )
            self._prev_total_pnl = self.strategy.total_pnl
            self._prev_position_size = int(position.size) if position else 0
            self._prev_avg_price = position.avg_price if position else 0.0
        except Exception as e:
            self.logger.error(f"Failed to save trading data snapshot: {e}")

        # Step 7: Generate dashboard data and save locally
        try:
            from .dashboard import generate_dashboard_data, save_dashboard_data

            dashboard_data = generate_dashboard_data(
                trading_data_dir=self.config.trading_data_dir,
                strategy_state_path=self.state_path,
                main_contract=self.main_contract,
                symbol=self.ctx.instrument_name,
                contract_multiplier=int(self.ctx.multiplier),
            )

            # Save locally
            dashboard_json_path = os.path.join(
                self.config.trading_data_dir, 'dashboard_data.json'
            )
            save_dashboard_data(dashboard_data, dashboard_json_path)
        except Exception as e:
            self.logger.error(f"Dashboard data generation failed: {e}")

        self.logger.info(
            f"Trading cycle completed in {duration:.1f}s | "
            f"status={results['status']}"
        )
        return results

    # =========================================================================
    # Trial Parameters
    # =========================================================================

    def _load_trial_params(self) -> Optional[Dict[str, Any]]:
        """
        Load trial parameters from the JSON file specified in config.

        Returns:
            Dictionary with 'params' key containing parameter values,
            or None if loading fails or path is not configured.
        """
        trial_path = self.config.trial_params_path
        if not trial_path:
            self.logger.info("No trial_params_path configured -- using default params")
            return None

        if not os.path.exists(trial_path):
            self.logger.warning(f"Trial params file not found: {trial_path}")
            return None

        try:
            with open(trial_path, "r") as f:
                config_data = json.load(f)

            if "params" not in config_data:
                self.logger.warning("No 'params' key in trial params file")
                return None

            trial_number = config_data.get("trial_number", "unknown")
            metrics = config_data.get("metrics", {})
            self.logger.info(
                f"Loaded trial params: trial={trial_number}, "
                f"sharpe={metrics.get('sharpe_ratio', 'N/A')}, "
                f"max_dd={metrics.get('max_drawdown_pct', 'N/A')}, "
                f"annual_return={metrics.get('annual_return', 'N/A')}"
            )
            return config_data["params"]

        except Exception as e:
            self.logger.error(f"Error loading trial params from {trial_path}: {e}")
            return None

    def _map_trial_params_to_strategy_params(
        self, trial_params: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Map flat trial params to nested strategy params structure.

        Trial params use prefixed naming (entry_X, exit_Y, risk_Z, sizer_W).
        Strategy expects nested dicts: entry_params, exit_params, etc.

        Uses DEFAULT_PARAMS as the base, overlaying any matching trial params.

        Args:
            trial_params: Flat dictionary of trial parameters with prefixed names.

        Returns:
            Nested strategy parameter dictionary.
        """
        from pathlib import Path
        from echolon.strategy.loader import StrategyLoader
        from echolon.config.settings import PLATFORM_AGNOSTIC_DIR

        loader = StrategyLoader(Path(PLATFORM_AGNOSTIC_DIR))
        DEFAULT_PARAMS = loader.load_attr("strategy_params", "DEFAULT_PARAMS")

        if not trial_params:
            self.logger.warning("No trial parameters -- using defaults")
            return DEFAULT_PARAMS

        # Start from defaults
        strategy_params = {}
        for key, value in DEFAULT_PARAMS.items():
            if isinstance(value, dict):
                strategy_params[key] = value.copy()
            else:
                strategy_params[key] = value

        # Prefix-to-component mapping
        prefix_map = {
            "entry_": "entry_params",
            "exit_": "exit_params",
            "risk_": "risk_params",
            "sizer_": "sizer_params",
            "size_": "sizer_params",  # Legacy prefix from old QTS_deploy
        }

        mapped_count = 0
        for param_name, param_value in trial_params.items():
            mapped = False
            for prefix, component_key in prefix_map.items():
                if param_name.startswith(prefix):
                    # Strip prefix to get the component-local param name
                    local_name = param_name[len(prefix):]
                    if component_key in strategy_params:
                        strategy_params[component_key][local_name] = param_value
                        mapped = True
                        mapped_count += 1
                        break

            # Handle non-prefixed params (top-level strategy params)
            if not mapped and param_name in strategy_params:
                strategy_params[param_name] = param_value
                mapped_count += 1

        self.logger.info(f"Mapped {mapped_count} trial params to strategy structure")
        return strategy_params

    def _load_and_map_trial_params(self) -> Dict[str, Any]:
        """Load trial params and map to strategy structure."""
        trial_params = self._load_trial_params()
        return self._map_trial_params_to_strategy_params(trial_params)

    # =========================================================================
    # Scheduling
    # =========================================================================

    def _schedule_daily_trading(self):
        """
        Set up APScheduler with a calendar-driven DateTrigger.

        Uses the trading calendar to find the exact next trading day,
        then determines the trigger time based on night market status.
        Replaces CronTrigger to avoid firing on holidays/weekends.
        """
        self.scheduler = BackgroundScheduler(timezone=self.TIMEZONE)

        # Ensure calendar exists before any queries
        self._ensure_trading_calendar()

        today = datetime.now()

        # Check if today is a trading day and schedule time hasn't passed
        target_date = None
        if is_trading_day(self.ctx.market_code, self.ctx.instrument_name, today):
            hour, minute = self._get_schedule_time(today)
            today_trigger_time = today.replace(
                hour=hour, minute=minute, second=0, microsecond=0
            )
            if today < today_trigger_time:
                target_date = today

        # If today isn't usable, find the next trading day
        if target_date is None:
            target_date = self._find_next_trading_day(today)

        if target_date is None:
            self.logger.error(
                "No future trading days found in 30-day lookahead — "
                "scheduler not started"
            )
            return

        hour, minute = self._get_schedule_time(target_date)
        run_date = self.TIMEZONE.localize(
            target_date.replace(hour=hour, minute=minute, second=0, microsecond=0)
        )

        self.scheduler.add_job(
            self._market_open_job,
            trigger=DateTrigger(run_date=run_date),
            name="DailyTradingJob",
            misfire_grace_time=self.config.misfire_grace_time,
        )

        self.scheduler.start()

        self.logger.info(
            f"Daily trading scheduled for {target_date.strftime('%Y-%m-%d')} "
            f"at {hour:02d}:{minute:02d} CST | run_date={run_date}"
        )

    def _market_open_job(self):
        """
        Job triggered by the scheduler at market open time.

        Full sequence:
        1. Check if trading day
        2. Update date and main contract
        3. Shut down previous engine if exists
        4. Re-initialize all components
        5. Execute trading cycle
        6. Reschedule next job based on tomorrow's night market
        """
        self.logger.info("=" * 70)
        self.logger.info("DAILY TRADING JOB TRIGGERED")
        self.logger.info("=" * 70)

        if not self.running:
            self.logger.warning("Runner not active -- skipping job")
            return

        # Ensure trading calendar exists before checking trading day
        self._ensure_trading_calendar()

        # Check if trading day
        if not is_trading_day(self.ctx.market_code, self.ctx.instrument_name, datetime.now()):
            self.logger.info("Not a trading day -- skipping cycle")
            self._reschedule_next_job()
            return

        # Update date (main contract resolved in _initialize after data pipeline)
        self.present_date = datetime.now()
        self.logger.info(f"Trading date: {self.present_date.strftime('%Y-%m-%d')}")

        # Shut down previous engine
        if self.engine or self.strategy:
            self.logger.info("Shutting down previous engine instance...")
            self._shutdown_engine()

        # Re-initialize and execute
        try:
            self._initialize()
            results = self._execute_trading_cycle()
            self.logger.info(f"Daily cycle results: {results.get('status', 'unknown')}")
        except Exception as e:
            self.logger.error(f"Daily trading cycle failed: {e}")
            self.logger.error(traceback.format_exc())

        # Reschedule for next day
        self._reschedule_next_job()

    def _reschedule_next_job(self):
        """
        Schedule the next trading job using the trading calendar.

        Finds the next trading day via get_trading_dates, determines
        the trigger time from night market status, and adds a new
        DateTrigger job (fired DateTriggers cannot be rescheduled).
        """
        if not self.scheduler:
            return

        try:
            today = datetime.now()
            next_day = self._find_next_trading_day(today)

            if next_day is None:
                self.logger.error(
                    "No future trading days found — cannot reschedule"
                )
                return

            hour, minute = self._get_schedule_time(next_day)
            run_date = self.TIMEZONE.localize(
                next_day.replace(hour=hour, minute=minute, second=0, microsecond=0)
            )

            # Remove the fired DateTrigger job
            for job in self.scheduler.get_jobs():
                if job.name == "DailyTradingJob":
                    job.remove()

            self.scheduler.add_job(
                self._market_open_job,
                trigger=DateTrigger(run_date=run_date),
                name="DailyTradingJob",
                misfire_grace_time=self.config.misfire_grace_time,
            )

            self.logger.info(
                f"Rescheduled: {next_day.strftime('%Y-%m-%d')} at "
                f"{hour:02d}:{minute:02d} | run_date={run_date}"
            )

        except Exception as e:
            self.logger.error(f"Rescheduling failed: {e}")
            self.logger.error("Will continue with existing schedule")

    def _get_schedule_time(self, date: datetime) -> tuple:
        """
        Determine schedule time (hour, minute) based on night market status.

        Args:
            date: Date to check night market status for.

        Returns:
            Tuple of (hour, minute) for scheduling.
        """
        try:
            night_open = is_night_market_open(self.ctx.market_code, self.ctx.instrument_name, date)

            if night_open:
                hour = self.config.night_market_schedule_hour
                minute = self.config.night_market_schedule_minute
                self.logger.info(
                    f"Schedule for {date.strftime('%Y-%m-%d')}: "
                    f"night market OPEN -> {hour:02d}:{minute:02d}"
                )
            else:
                hour = self.config.day_only_schedule_hour
                minute = self.config.day_only_schedule_minute
                self.logger.info(
                    f"Schedule for {date.strftime('%Y-%m-%d')}: "
                    f"night market CLOSED -> {hour:02d}:{minute:02d}"
                )

            return hour, minute

        except Exception as e:
            self.logger.error(f"Error determining schedule time: {e}")
            # Fallback to night market time (conservative)
            return (
                self.config.night_market_schedule_hour,
                self.config.night_market_schedule_minute,
            )

    def _find_next_trading_day(self, after_date: datetime) -> Optional[datetime]:
        """
        Find the next trading day strictly after after_date.

        Uses get_trading_dates with a 30-day lookahead window.

        Args:
            after_date: Find trading days after this date.

        Returns:
            The next trading day as a datetime, or None if none found.
        """
        start = after_date + timedelta(days=1)
        end = after_date + timedelta(days=30)

        trading_dates = get_trading_dates(
            self.ctx.market_code,
            self.ctx.instrument_name,
            start_date=start.strftime("%Y-%m-%d"),
            end_date=end.strftime("%Y-%m-%d"),
        )

        if not trading_dates:
            return None

        first = trading_dates[0]
        # Convert pd.Timestamp to datetime if needed
        if hasattr(first, 'to_pydatetime'):
            first = first.to_pydatetime()
        return first

    # =========================================================================
    # Callbacks
    # =========================================================================

    def _on_order_update(self, order):
        """Callback for QMT order status updates.

        Stores latest order data in _order_events and signals the Event
        when a terminal status is reached (filled/cancelled/rejected).

        Args:
            order: XtOrder object from xtquant (attribute access, not dict).
        """
        order_id = getattr(order, "order_id", "N/A")
        order_status = getattr(order, "order_status", 0)
        traded_price = getattr(order, "traded_price", 0.0)
        traded_volume = getattr(order, "traded_volume", 0)
        status_msg = getattr(order, "status_msg", "")

        self.logger.info(
            f"Order update: id={order_id}, status={order_status}, "
            f"traded={traded_volume}@{traded_price}, msg={status_msg}"
        )

        # Forward to strategy logger if available
        if (
            self.strategy
            and hasattr(self.strategy, "strategy_logger")
            and self.strategy.strategy_logger
        ):
            try:
                order_data = {
                    "action": "status_update",
                    "ref": str(order_id),
                    "status": str(order_status),
                    "side": str(getattr(order, "order_type", "")),
                    "size": getattr(order, "order_volume", 0),
                    "price": getattr(order, "price", 0),
                }
                self.strategy.strategy_logger.log_order_event(order_data)
            except Exception as e:
                self.logger.error(f"Error logging order event: {e}")

        # Store callback data and signal event on terminal status
        if order_id not in self._order_events:
            self._order_events[order_id] = {
                'event': threading.Event(),
                'status': 0,
                'traded_price': 0.0,
                'traded_volume': 0,
                'status_msg': '',
            }
        entry = self._order_events[order_id]
        entry['status'] = order_status
        entry['traded_price'] = traded_price
        entry['traded_volume'] = traded_volume
        entry['status_msg'] = status_msg
        # Terminal: not unreported(48)/wait_reporting(49)/reported(50)
        if order_status not in (48, 49, 50):
            entry['event'].set()

    def _on_trade_update(self, trade):
        """Callback for QMT trade execution updates.

        Updates _order_events with the actual execution price/volume so that
        _wait_and_log_executions picks up the real fill price even when the
        order-status callback arrives before the trade callback.
        """
        trade_id = getattr(trade, "order_id", "N/A")
        traded_price = getattr(trade, "traded_price", 0.0)
        traded_volume = getattr(trade, "traded_volume", 0)
        self.logger.info(
            f"Trade update: id={trade_id}, price={traded_price}, volume={traded_volume}"
        )

        # Write execution price into _order_events so the logger picks it up
        if trade_id in self._order_events and traded_price > 0:
            self._order_events[trade_id]['traded_price'] = traded_price
            self._order_events[trade_id]['traded_volume'] = traded_volume

    def _on_market_data_update(self, market_data):
        """Callback for QMT market data updates."""
        self.logger.debug(f"Market data update: {market_data}")

    # =========================================================================
    # Signal Handling
    # =========================================================================

    def _signal_handler(self, signum, frame):
        """Handle SIGINT/SIGTERM for graceful shutdown."""
        sig_name = signal.Signals(signum).name
        self.logger.info(f"Received {sig_name} -- initiating shutdown")
        self.stop()

    # =========================================================================
    # Internal Helpers
    # =========================================================================

    def _ensure_trading_calendar(self):
        """Generate trading calendar if it doesn't exist yet.

        Called before is_trading_day() to ensure the calendar CSV is
        available. Uses the static calendar shipped in deploy/config/.
        """
        market = self.ctx.market_code
        instrument = self.ctx.instrument_name
        calendar_dir = MARKET_DATA_DIR / market / instrument
        calendar_file = calendar_dir / "trading_calendar.csv"

        if calendar_file.exists():
            return

        self.logger.info("Trading calendar not found — generating from static source")
        from echolon.data.extractors.shfe.api_day_extractor import SHFEApiDayExtractor
        extractor = SHFEApiDayExtractor(market=market, asset=instrument)
        extractor.generate_trading_calendar(
            source_path=self.config.trading_calendar_path,
            output_dir=str(calendar_dir),
        )

    def _wait_and_log_executions(self, logger_bar: dict, timeout: float = 600.0):
        """Wait for callback results and log trade executions.

        For each submitted order this cycle, waits up to `timeout` seconds
        for the async _on_order_update callback to report a terminal status.
        Always logs the trade execution regardless of outcome.

        Args:
            logger_bar: Captured strategy logger bar data.
            timeout: Max seconds to wait for each order (default 10 min).
        """
        order_mgr = self.engine.get_order_manager()
        submitted = [
            o for o in order_mgr._orders.values()
            if o.status == OrderStatus.SUBMITTED and 'qmt_order_id' in o.metadata
        ]

        if not submitted:
            return

        STATUS_MAP = {
            48: 'UNREPORTED', 49: 'WAIT_REPORTING', 50: 'SUBMITTED',
            55: 'PARTIAL_FILLED', 56: 'FILLED',
            53: 'PARTIAL_CANCELED', 54: 'CANCELED', 57: 'REJECTED',
        }

        for order in submitted:
            qmt_id = order.metadata['qmt_order_id']

            # Register event for this order (callback will signal it)
            entry = self._order_events.get(qmt_id)
            if entry is None:
                entry = {
                    'event': threading.Event(),
                    'status': 0,
                    'traded_price': 0.0,
                    'traded_volume': 0,
                    'status_msg': '',
                }
                self._order_events[qmt_id] = entry

            # Wait for callback to report terminal status
            self.logger.info(f"Waiting for order {qmt_id} callback (timeout={timeout}s)...")
            filled = entry['event'].wait(timeout=timeout)

            status = entry['status']
            traded_price = entry['traded_price']
            traded_volume = entry['traded_volume']
            status_msg = entry['status_msg']
            exec_status = STATUS_MAP.get(status, f'UNKNOWN_{status}')

            if filled:
                # Trade callback may arrive shortly after the order terminal
                # status.  Wait briefly so _on_trade_update can write the real
                # execution price into _order_events.
                if entry['traded_price'] == 0.0 and status == 56:
                    time.sleep(2.0)

                # Re-read after potential trade callback update
                traded_price = entry['traded_price']
                traded_volume = entry['traded_volume']

                self.logger.info(
                    f"Order {qmt_id} callback received: status={status}({exec_status}), "
                    f"traded={traded_volume}@{traded_price}, msg={status_msg}"
                )
            else:
                self.logger.warning(
                    f"Order {qmt_id} callback timed out after {timeout}s. "
                    f"Last known: status={status}({exec_status}), "
                    f"traded={traded_volume}@{traded_price}"
                )
                if status == 0:
                    exec_status = 'TIMEOUT_NO_CALLBACK'

            # Update Order object
            if traded_volume > 0:
                order.filled_size = traded_volume
                order.filled_price = traded_price
                order.filled_at = datetime.now()
            if status == 56:
                order.status = OrderStatus.FILLED
            elif status == 54:
                order.status = OrderStatus.CANCELLED
            elif status == 57:
                order.status = OrderStatus.REJECTED

            # Refresh portfolio from QMT so position data reflects the fill
            try:
                self.engine.refresh()
            except Exception as e:
                self.logger.warning(f"Portfolio refresh after fill failed: {e}")

            # Log trade execution — always, with both submission and fill data
            portfolio = self.engine.get_portfolio()
            position = portfolio.get_position()
            save_trade_execution(
                trading_data_dir=self.config.trading_data_dir,
                order_info={
                    'order_id': str(qmt_id),
                    'direction': order.intent.value if order.intent else '',
                    'order_type': 'MARKET',
                    'submitted_price': order.price if order.price else 0.0,
                    'submitted_size': order.size if order.size else 0,
                },
                execution_details={
                    'executed_price': traded_price,
                    'executed_size': traded_volume,
                    'commission': 0.0,
                    'status': exec_status,
                },
                position_impact={
                    'position_before': self._prev_position_size,
                    'position_after': int(position.size) if position else 0,
                    'avg_price_before': self._prev_avg_price,
                    'avg_price_after': position.avg_price if position else 0.0,
                },
                pnl_impact={
                    'realized_pnl': 0.0,
                    'unrealized_pnl': portfolio.get_unrealized_pnl(),
                },
                symbol=self.ctx.instrument_name,
            )

            # Cleanup
            self._order_events.pop(qmt_id, None)

    def _shutdown_engine(self):
        """Shut down the current engine and strategy without full stop."""
        # Finalize strategy logging
        if self.strategy and hasattr(self.strategy, "strategy_logger"):
            try:
                if self.strategy.strategy_logger:
                    self.strategy.strategy_logger.finalize_logging()
            except Exception as e:
                self.logger.error(f"Error finalizing strategy logger: {e}")

        # Disconnect client (will reconnect during next initialization)
        if self.client:
            try:
                self.client.disconnect()
            except Exception as e:
                self.logger.error(f"Error disconnecting client: {e}")
            self.client = None

        self.engine = None
        self.strategy = None

    def _get_calendar_path(self) -> str:
        """Get path to the deploy trading calendar CSV."""
        return self.config.calendar_path

    def _get_indicators_path(self) -> str:
        """Get path to strategy indicators CSV for this instrument."""
        instrument = self.ctx.instrument_name
        return os.path.join(
            self.config.indicator_dir, instrument, "strategy_indicators.csv"
        )
