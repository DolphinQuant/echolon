"""
Backtrader Strategy Bridge
==========================

Bridge between Backtrader's bt.Strategy and platform-agnostic strategy code.

This module provides get_strategy_class() which returns a configured
BacktraderStrategyBridge class that:
1. Implements Backtrader's bt.Strategy interface
2. Delegates trading logic to platform-agnostic strategy components
3. Uses ITradingEngine for all market data and order operations
4. Integrates with strategy logger for systematic output

Hook-Based Architecture:
    Market/frequency-specific features are handled via strategy hooks:
    - ForcedExitStrategyHook: Contract expiry handling (interday futures)
    - SessionAwareStrategyHook: Session context (intraday trading)

    Hooks are added to the strategy and called during BaseStrategy.on_bar()
    lifecycle via the Template Method pattern.

Architecture:
    BacktraderStrategyBridge (bt.Strategy)
        └── strategy_main (platform-agnostic)
                ├── hooks (ForcedExit, SessionAware, etc.)
                ├── entry_rule
                ├── exit_rule
                ├── risk_manager
                └── position_sizer
"""

from typing import Dict, Any, Type, Optional, TYPE_CHECKING
import backtrader as bt
import logging
from ...data_loader.SHFE_loader import load_indicator_metadata
from ...core.interfaces.trading_interfaces import OrderStatus
from ...logging_utils import get_run_context, should_log_details

if TYPE_CHECKING:
    from .backtrader_engine import BacktraderEngine

module_logger = logging.getLogger(__name__)


class BacktraderStrategyBridge(bt.Strategy):
    """
    Bridge between Backtrader and platform-agnostic strategy.

    Hook-based architecture:
    - Market/frequency-specific features handled via strategy hooks
    - ForcedExitStrategyHook: Processes forced exits in on_bar_start()
    - SessionAwareStrategyHook: Provides session context helpers

    This class:
    1. Receives bar events from Backtrader (next())
    2. Updates engine's market data references
    3. Delegates to platform-agnostic strategy via on_bar()
       (hooks are called automatically in BaseStrategy.on_bar())
    4. Logs all events to strategy logger
    """

    params = (
        ('engine', None),
        ('strategy_name', 'default'),
        ('market', 'SHFE'),
        ('instrument', 'aluminum'),  # Full name for metadata paths
        ('instrument_code', 'al'),   # Code for trading operations
        ('strategy_params', {}),
        ('printlog', True),
    )

    def __init__(self):
        """Initialize bridge with engine reference."""
        self._engine: Optional['BacktraderEngine'] = self.params.engine
        self._strategy_name = self.params.strategy_name
        self._market = self.params.market
        self._instrument = self.params.instrument  # Full name for metadata paths
        self._instrument_code = self.params.instrument_code  # Code for trading
        self._strategy_params = self.params.strategy_params
        self._printlog = self.params.printlog

        # Update engine components with Backtrader data feed
        if self._engine is not None:
            self._engine._market_data.set_data_feed(self.data)
            self._engine._portfolio.set_data_feed(self.data)
            self._engine._portfolio.set_broker(self.broker)
            self._engine._order_manager.set_strategy(self)
            self._engine._order_manager.set_data_feed(self.data)
            self._engine._order_manager.set_symbol(self._instrument_code)

        # Trade tracking
        self._trade_count = 0
        self._pending_orders = {}
        self._bar_count = 0

        # Cache strategy logger reference (avoids repeated method calls)
        self._strategy_logger = self._engine.get_strategy_logger() if self._engine else None

        # Register all available indicators with the trading engine BEFORE creating strategy
        self._register_indicators()

        # Initialize platform-agnostic strategy immediately
        self._agnostic_strategy = None
        self._start_called = False
        self._initialize_strategy()

        self.log(f"BacktraderStrategyBridge initialized: {self._strategy_name}")
        self.log(f"  Market: {self._market}, Instrument: {self._instrument} ({self._instrument_code})")
        freq_ctx = self._engine.get_frequency_context()
        if freq_ctx is not None:
            self.log(f"  Frequency: {freq_ctx.bar_size}")

    @property
    def agnostic_strategy(self):
        """Expose agnostic strategy for observers (e.g., contract expiry observer)."""
        return self._agnostic_strategy

    def log(self, txt: str, dt=None):
        """Log message with timestamp."""
        if self._printlog:
            dt = dt or self.data.datetime.date(0)
            print(f'{dt.isoformat()} {txt}')

    def _register_indicators(self):
        """
        Register all available data feed indicators with the trading engine.

        This method reads indicator metadata and registers each indicator line
        from the Backtrader data feed with the market data interface.
        """
        ctx = self._engine.get_trading_context()
        # Use per-slot metadata path if strategy_code_dir is set
        code_dir = self.p.strategy_code_dir
        if code_dir is not None:
            from pathlib import Path
            from config.quant_engine import INDICATOR_DIR
            slot_meta = Path(INDICATOR_DIR) / Path(code_dir).name / "strategy_indicator_metadata.json"
            metadata = load_indicator_metadata(ctx=ctx, metadata_path=str(slot_meta) if slot_meta.exists() else None)
        else:
            metadata = load_indicator_metadata(ctx=ctx)

        registered_indicators = []
        failed_indicators = []

        if 'indicator_columns' in metadata:
            # Filter out non-numeric columns
            excluded_columns = {'date', 'contract', 'unnamed: 14', 'trading_date'}
            indicator_columns = [col for col in metadata['indicator_columns']
                               if col.lower() not in excluded_columns]

            for col in indicator_columns:
                # Convert to lowercase for line name (backtrader convention)
                line_name = col.lower()

                # Try to get the indicator from the data feed
                if hasattr(self.data, line_name):
                    indicator = getattr(self.data, line_name)
                    # Check if it's a line (indicator) by seeing if it has array-like access
                    if hasattr(indicator, '__getitem__'):
                        self._engine._market_data.register_indicator(line_name, indicator)
                        registered_indicators.append(line_name)
                    else:
                        failed_indicators.append(f"{line_name} (not array-like)")
                else:
                    failed_indicators.append(f"{line_name} (not found)")

        # Log indicator registration
        if module_logger.isEnabledFor(logging.INFO):
            module_logger.info(f"[STRATEGY_BRIDGE] Indicators | registered={len(registered_indicators)}")
            if failed_indicators:
                module_logger.warning(f"[STRATEGY_BRIDGE] Indicators | failed={len(failed_indicators)} (first 10: {failed_indicators[:10]})")

    def _initialize_strategy(self):
        """
        Initialize platform-agnostic strategy with appropriate hooks.

        Called once in __init__. Adds strategy hooks based on trading mode:
        - ForcedExitStrategyHook: For interday futures (contract expiry)
        - SessionAwareStrategyHook: For intraday trading (session context)

        If strategy_code_dir param is set, loads strategy from that directory
        via importlib instead of the default platform_agnostic package.
        """
        code_dir = self.p.strategy_code_dir
        if code_dir is not None:
            # Load strategy from custom directory (portfolio slot).
            # The slot's strategy.py uses relative imports like
            # "from ...core.base.base_strategy import BaseStrategy"
            # so it must be loaded as a proper sub-package of
            # modules.quant_engine.strategy.
            import importlib
            from pathlib import Path
            slot_dir = Path(code_dir)
            slot_name = slot_dir.name  # e.g. "al_s1"
            package_name = f"modules.quant_engine.strategy.{slot_name}"

            # Ensure __init__.py exists so Python treats it as a package
            init_path = slot_dir / "__init__.py"
            if not init_path.exists():
                init_path.touch()

            # Import as a proper package so relative imports resolve
            mod = importlib.import_module(f"{package_name}.strategy")
            strategy_main = mod.strategy_main
        else:
            # Default: load from platform_agnostic package
            from ...strategy.platform_agnostic.strategy import strategy_main

        # Create strategy instance with engine.
        # When using a custom slot dir, inject slot_id so BaseStrategy
        # resolves components from the slot package instead of platform_agnostic.
        extra_kwargs = {}
        if code_dir is not None:
            extra_kwargs['slot_id'] = Path(code_dir).name

        self._agnostic_strategy = strategy_main(
            trading_engine=self._engine,
            **self._strategy_params,
            **extra_kwargs,
        )

        # Add strategy hooks based on trading mode
        self._add_strategy_hooks()

        # Strategy's on_start is called in start() method
        # This matches the old architecture where on_start is called once

    def _add_strategy_hooks(self):
        """
        Add strategy hooks based on engine's market adapter and frequency context.

        Hook Composition:
            | Market | Frequency | ForcedExitHook | SessionAwareHook |
            |--------|-----------|----------------|------------------|
            | SHFE   | Interday  | ✅             | ❌               |
            | SHFE   | Intraday  | ❌             | ✅               |
            | Crypto | Intraday  | ❌             | ✅               |
            | Crypto | Interday  | ❌             | ❌               |
        """
        from ...core.interfaces.frequency_context import FrequencyType

        market_adapter = self._engine.get_market_adapter()
        frequency_context = self._engine.get_frequency_context()

        if market_adapter is None or frequency_context is None:
            return

        has_contract_expiry = getattr(market_adapter, 'has_contract_expiry', False)
        is_interday = frequency_context.frequency_type == FrequencyType.INTERDAY
        is_intraday = frequency_context.frequency_type == FrequencyType.INTRADAY

        hooks_added = []

        # ForcedExitStrategyHook: For interday futures trading
        if has_contract_expiry and is_interday:
            from ...core.base.hooks.forced_exit_strategy_hook import ForcedExitStrategyHook
            self._agnostic_strategy.add_hook(ForcedExitStrategyHook(market_adapter))
            hooks_added.append("ForcedExitStrategyHook")

        # SessionAwareStrategyHook: For intraday trading
        if is_intraday:
            from ...core.base.hooks.session_aware_strategy_hook import SessionAwareStrategyHook
            self._agnostic_strategy.add_hook(SessionAwareStrategyHook())
            hooks_added.append("SessionAwareStrategyHook")

        if hooks_added:
            self.log(f"Strategy hooks added: {', '.join(hooks_added)}")

    def start(self):
        """
        Called when the strategy starts (Backtrader lifecycle).

        Following old architecture pattern: call on_start() once here.
        """
        if not self._start_called:
            self._agnostic_strategy.on_start()
            self._start_called = True

    def notify_order(self, order):
        """
        Handle Backtrader order notifications.

        BACKWARD COMPATIBLE: Logs order events to strategy logger.
        """
        # Update order status in order manager
        status_map = {
            order.Submitted: OrderStatus.SUBMITTED,
            order.Accepted: OrderStatus.ACCEPTED,
            order.Completed: OrderStatus.FILLED,
            order.Canceled: OrderStatus.CANCELLED,
            order.Margin: OrderStatus.REJECTED,
            order.Rejected: OrderStatus.REJECTED,
        }
        new_status = status_map.get(order.status, OrderStatus.PENDING)
        self._engine._order_manager.update_order_status(order.ref, new_status)

        if order.status in [order.Submitted, order.Accepted]:
            return

        if order.status == order.Completed:
            action = 'BUY' if order.isbuy() else 'SELL'
            self.log(f'{action} EXECUTED: Price={order.executed.price:.2f}, '
                     f'Size={order.executed.size}, Comm={order.executed.comm:.2f}')

            # Log to strategy logger
            if self._strategy_logger is not None:
                self._strategy_logger.log_order_event({
                    'action': 'executed',
                    'status': 'Executed',
                    'ref': order.ref,
                    'side': action,
                    'price': order.executed.price,
                    'size': order.executed.size,
                    'commission': order.executed.comm,
                    'datetime': self.data.datetime.datetime(0).isoformat(),
                })

        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            status_name = order.Status[order.status]
            self.log(f'Order Failed: {status_name}')

            # Log to strategy logger
            if self._strategy_logger is not None:
                self._strategy_logger.log_order_event({
                    'action': 'failed',
                    'status': status_name,
                    'ref': order.ref,
                    'datetime': self.data.datetime.datetime(0).isoformat(),
                })

    def notify_trade(self, trade):
        """
        Handle Backtrader trade notifications.

        BACKWARD COMPATIBLE: Logs trade events to strategy logger.
        """
        if not trade.isclosed:
            return

        self._trade_count += 1
        self.log(f'TRADE #{self._trade_count} CLOSED: '
                 f'PnL Gross={trade.pnl:.2f}, Net={trade.pnlcomm:.2f}')

        # Add realized PnL to portfolio tracker
        self._engine._portfolio.add_realized_pnl(trade.pnlcomm)

        # Log to strategy logger
        if self._strategy_logger is not None:
            self._strategy_logger.log_trade_event({
                'trade_id': self._trade_count,
                'pnl_gross': trade.pnl,
                'pnl_net': trade.pnlcomm,
                'commission': trade.commission,
                'datetime': self.data.datetime.datetime(0).isoformat(),
            })

    def next(self):
        """
        Called on each bar - main entry point for strategy logic.

        Hook-based architecture: All market/frequency-specific features
        (forced exits, session context) are handled via strategy hooks
        in BaseStrategy.on_bar() lifecycle:
        1. hook.on_bar_start() - ForcedExitStrategyHook processes exits here
        2. strategy._execute_bar() - Strategy-specific logic
        3. hook.on_bar_end() - Cleanup
        """
        self._bar_count += 1

        # Get context for conditional logging
        run_context = get_run_context()
        log_details = should_log_details(run_context)

        # Log bar start (debug/best_trial only)
        if log_details:
            current_price = self.data.close[0]
            position_size = self.broker.getposition(self.data).size
            module_logger.info(
                f"[{run_context.upper()}] Bar {self._bar_count} | START | "
                f"datetime={self.data.datetime.datetime(0).isoformat()}, "
                f"price={current_price:.2f}, position={position_size}"
            )

        # Start new bar in strategy logger
        if self._strategy_logger is not None and hasattr(self._strategy_logger, 'start_new_bar'):
            self._strategy_logger.start_new_bar()
            self._strategy_logger.log_strategy_state({
                'bar_count': self._bar_count,
                'datetime': self.data.datetime.datetime(0).strftime('%Y-%m-%d %H:%M:%S'),
            })

        # Delegate to platform-agnostic strategy
        # Hook lifecycle (forced exits, session context) handled in on_bar()
        self._agnostic_strategy.on_bar()

        # Log bar end with position change detection (debug/best_trial only)
        if log_details:
            new_position_size = self.broker.getposition(self.data).size
            position_changed = new_position_size != position_size
            equity = self.broker.getvalue()
            module_logger.info(
                f"[{run_context.upper()}] Bar {self._bar_count} | END | "
                f"position={new_position_size}, changed={position_changed}, equity={equity:.2f}"
            )

        # Finalize bar in strategy logger
        if self._strategy_logger is not None and hasattr(self._strategy_logger, 'finalize_bar'):
            self._strategy_logger.finalize_bar()

    def stop(self):
        """Called when backtest ends."""
        # Call strategy's on_stop if available
        self._agnostic_strategy.on_stop()

        # Finalize strategy logger
        if self._strategy_logger is not None:
            log_path = self._strategy_logger.finalize_logging()
            if log_path:
                self.log(f'Strategy log saved to: {log_path}')

        self.log(f'Strategy finished. Total trades: {self._trade_count}')
        self.log(f'Final Portfolio Value: {self.broker.getvalue():,.2f}')


# Cache for dynamically created strategy classes (for pickle compatibility)
_STRATEGY_CLASS_CACHE: Dict[str, Type[bt.Strategy]] = {}

from config.markets.core.context import TradingContext


def get_strategy_class(ctx: TradingContext, strategy_code_dir: Optional[str] = None) -> Type[bt.Strategy]:
    """
    Get Backtrader-compatible strategy class based on TradingContext.

    This function configures BacktraderStrategyBridge with ctx values,
    returning a class ready for Cerebro. The engine is injected separately
    by engine.setup() via strategy_params.

    The class is cached and registered in the module namespace to enable
    pickle serialization for multiprocessing (Optuna optimization).

    Args:
        ctx: TradingContext (single source of truth for market/instrument config)
        strategy_code_dir: Optional path to strategy code directory.
            If provided, strategy is loaded from this directory via importlib
            instead of from strategy/platform_agnostic/.

    Returns:
        BacktraderStrategyBridge class configured with ctx params
    """
    strategy_name = 'default'
    market = ctx.market_code
    instrument = ctx.instrument_name
    instrument_code = ctx.instrument_code

    # Create a unique cache key based on config values
    # Include strategy_code_dir so different slots get different classes
    cache_key = f"{strategy_name}_{market}_{instrument}_{instrument_code}_{strategy_code_dir or 'default'}"

    # Return cached class if exists (required for pickle compatibility)
    if cache_key in _STRATEGY_CLASS_CACHE:
        return _STRATEGY_CLASS_CACHE[cache_key]

    # Create class name that's valid for pickle
    class_name = f'Bridge_{strategy_name}'

    # Create subclass with config-based params
    # Engine will be injected by engine.setup() via strategy_params
    strategy_class = type(
        class_name,
        (BacktraderStrategyBridge,),
        {
            'params': (
                ('engine', None),  # Injected by engine.setup()
                ('strategy_name', strategy_name),
                ('market', market),
                ('instrument', instrument),  # Full name for metadata paths
                ('instrument_code', instrument_code),  # Code for trading
                ('strategy_params', {}),
                ('strategy_code_dir', strategy_code_dir),  # Custom strategy dir (None = platform_agnostic)
                ('printlog', True),
            )
        }
    )

    # Register class in module namespace for pickle compatibility
    # Pickle requires the class to be findable via module.class_name
    strategy_class.__module__ = __name__
    strategy_class.__qualname__ = class_name
    globals()[class_name] = strategy_class

    # Cache the class
    _STRATEGY_CLASS_CACHE[cache_key] = strategy_class

    return strategy_class
