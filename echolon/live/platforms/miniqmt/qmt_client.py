"""
MiniQMT Client
==============

Low-level wrapper for MiniQMT API (xtquant).

Ported from QTS_deploy/miniqmt/miniqmt_client.py with the following changes:
- Uses QMTAccountConfig from deploy_config instead of old TradeConfig
- Proper relative imports (no sys.path hacks)
- Standard logging via logging.getLogger(__name__)
- EXEMPT from no-try-except policy (external API boundary)

Handles:
- Connection management (connect, disconnect)
- Order placement with night market scheduling (APScheduler)
- Position and account queries
- Callback registration for order/trade events

Reference:
- Data API: https://dict.thinktrader.net/nativeApi/xtdata.html
- Trading API: https://dict.thinktrader.net/nativeApi/xttrader.html
"""

import datetime
import logging
import os
import random
import threading
import time
import traceback
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple

import pandas as pd
import pytz
# APScheduler disabled — dedicated threads used instead (GIL starvation fix)
# from apscheduler.schedulers.background import BackgroundScheduler
# from apscheduler.triggers.date import DateTrigger

from xtquant import xtconstant, xtdata
from xtquant.xttrader import XtQuantTrader, XtQuantTraderCallback
from xtquant.xttype import StockAccount

from ...config.deploy_config import QMTAccountConfig
from echolon.data.loaders.calendar_loader import is_night_market_open
from echolon.errors import raise_error

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Error helpers (LIV-001)
# ---------------------------------------------------------------------------


def _raise_broker_unavailable(account_id: str, error: str) -> None:
    """Raise LIV-001 when the miniQMT client can't connect or loses connection."""
    raise_error(
        "LIV-001",
        platform="miniqmt",
        account_id=account_id,
        error=error,
    )


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class OrderInfo:
    """Order information structure."""
    order_id: int
    symbol: str
    intent: str
    price: float
    volume: int
    order_type: str
    timestamp: datetime.datetime
    status: str = "PENDING"


@dataclass
class PositionInfo:
    """Position information structure."""
    symbol: str
    volume: int
    avg_price: float
    unrealized_pnl: float
    market_value: float
    direction: str


# ---------------------------------------------------------------------------
# Callback
# ---------------------------------------------------------------------------

class MiniQMTCallback(XtQuantTraderCallback):
    """Callback handler for miniQMT events."""

    def __init__(self, client: "MiniQMTClient"):
        super().__init__()
        self.client = client

    def on_disconnected(self):
        """Handle disconnection events."""
        logger.warning("miniQMT connection lost!")
        self.client.is_connected = False

    def on_order_stock_async_response(self, response):
        """Handle async order response — maps seq_id to real order_id.

        Called by xtquant after order_stock_async(). The response object
        contains .seq (the sequence ID returned by order_stock_async)
        and .order_id (the real exchange order ID used in all subsequent
        callbacks).
        """
        seq = getattr(response, 'seq', 0)
        order_id = getattr(response, 'order_id', 0)
        logger.info("Async response: seq=%s -> order_id=%s", seq, order_id)
        if hasattr(self.client, "async_response_callback") and self.client.async_response_callback:
            self.client.async_response_callback(seq, order_id)

    def on_stock_order(self, order):
        """Handle order status updates."""
        logger.info(
            "Order update: %s - Status: %s", order.order_id, order.order_status
        )
        if hasattr(self.client, "order_callback") and self.client.order_callback:
            self.client.order_callback(order)

    def on_stock_trade(self, trade):
        """Handle trade execution updates."""
        logger.info(
            "Trade executed: %s - Price: %s, Volume: %s",
            trade.order_id,
            trade.traded_price,
            trade.traded_volume,
        )
        if hasattr(self.client, "trade_callback") and self.client.trade_callback:
            self.client.trade_callback(trade)


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

class MiniQMTClient:
    """
    Main client class for interacting with miniQMT platform.

    Features:
    - Connection management with automatic reconnection
    - Market data downloading and retrieval
    - Real-time data subscription and streaming
    - Order placement and management (with night-market scheduling)
    - Position monitoring
    - Error handling and logging
    """

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    def __init__(
        self,
        config: QMTAccountConfig,
        session_id: Optional[int] = None,
        market: Optional[str] = None,
        asset: Optional[str] = None,
    ):
        """
        Initialize the miniQMT client.

        Args:
            config: QMTAccountConfig with qmt_path, account_id, account_type.
            session_id: Explicit session ID.  Generated randomly if None.
            market: Market code (e.g., "SHFE") for calendar lookups.
            asset: Asset name (e.g., "aluminum") for calendar lookups.
        """
        self.config = config
        self.session_id = session_id
        self.market = market
        self.asset = asset

        self.trader: Optional[XtQuantTrader] = None
        self.account: Optional[StockAccount] = None
        self.is_connected: bool = False
        self.is_subscribed: bool = False

        # Real-time data subscription management
        self.subscribed_symbols: set = set()
        self.realtime_data_cache: Dict[str, Any] = {}

        # Callbacks
        self.order_callback: Optional[Callable] = None
        self.trade_callback: Optional[Callable] = None
        self.market_data_callback: Optional[Callable] = None

        # Data storage
        self.market_data_cache: Dict[str, Any] = {}
        self.orders: Dict[int, OrderInfo] = {}
        self.positions: Dict[str, PositionInfo] = {}

        # Scheduled order management
        self.scheduled_orders: Dict[str, Any] = {}
        # self.order_scheduler: Optional[BackgroundScheduler] = None  # APScheduler disabled
        self.temp_order_counter: int = 0

        # Thread safety
        self.data_lock = threading.Lock()
        self.order_lock = threading.Lock()
        self.subscription_lock = threading.Lock()
        self.scheduler_lock = threading.Lock()

        # Reconnection settings
        self.max_reconnect_attempts: int = 5
        self.reconnect_delay: int = 30  # seconds

        logger.info("MiniQMT Client initialized for account: %s", config.account_id)

        # APScheduler disabled — dedicated threads used instead
        # self._initialize_order_scheduler()

    # ------------------------------------------------------------------
    # Scheduler
    # ------------------------------------------------------------------

    # def _initialize_order_scheduler(self):
    #     """Initialize the APScheduler for delayed order execution."""
    #     try:
    #         tz = pytz.timezone("Asia/Shanghai")
    #         self.order_scheduler = BackgroundScheduler(timezone=tz)
    #         self.order_scheduler.start()
    #         logger.info("APScheduler initialized successfully for order scheduling")
    #     except Exception as exc:
    #         logger.error("Failed to initialize order scheduler: %s", exc)
    #         self.order_scheduler = None

    def _should_execute_immediately(self, scheduled_time: datetime.datetime) -> bool:
        """Check if order should be executed immediately based on current time."""
        try:
            shanghai_tz = pytz.timezone("Asia/Shanghai")
            now = datetime.datetime.now(shanghai_tz)

            # If scheduled_time is naive, assume Shanghai timezone
            if scheduled_time.tzinfo is None:
                scheduled_time = shanghai_tz.localize(scheduled_time)

            return now >= scheduled_time

        except Exception as exc:
            logger.error("Error checking execution time: %s", exc)
            return True  # Default to immediate execution on error

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------

    def connect(self) -> bool:
        """
        Connect to miniQMT platform.

        Returns:
            True if connection successful, False otherwise.
        """
        try:
            # Generate session ID if not provided
            if self.session_id is None:
                self.session_id = int(random.randint(100000, 999999))

            logger.info("Connecting to miniQMT with session: %s", self.session_id)

            # Check if QMT path exists
            if not os.path.exists(self.config.qmt_path):
                logger.error("QMT path does not exist: %s", self.config.qmt_path)
                return False

            # Initialize trader
            self.trader = XtQuantTrader(self.config.qmt_path, self.session_id)
            logger.info("QMT Path: %s", self.config.qmt_path)
            logger.info("Session ID: %s", self.session_id)

            # Set callback
            callback = MiniQMTCallback(self)
            self.trader.register_callback(callback)

            # Start trader
            logger.info("Starting XtQuantTrader...")
            self.trader.start()

            # Wait for startup
            time.sleep(3)

            # Connect
            logger.info("Attempting to connect to miniQMT...")
            connect_result = self.trader.connect()
            if connect_result != 0:
                logger.error(
                    "Failed to connect to miniQMT. Error code: %s", connect_result
                )
                return False

            logger.info("Successfully connected to miniQMT")

            # Set up account
            if not self._setup_account():
                return False

            self.is_connected = True
            return True

        except Exception as exc:
            logger.error("Connection error: %s", exc)
            logger.error("Full traceback: %s", traceback.format_exc())
            return False

    def _setup_account(self) -> bool:
        """Set up trading account."""
        self.account = StockAccount(
            self.config.account_id, self.config.account_type
        )

        # Subscribe to account
        subscribe_result = self.trader.subscribe(self.account)
        if subscribe_result != 0:
            logger.error("Failed to subscribe to account: %s", subscribe_result)
            return False

        self.is_subscribed = True
        logger.info(
            "Successfully subscribed to account: %s", self.config.account_id
        )

        # Get account info
        account_info = self.trader.query_stock_asset(self.account)
        if account_info:
            available_cash = account_info.m_dCash
            logger.info(
                "Account %s - Available cash: %.2f",
                self.config.account_id,
                available_cash,
            )

        return True

    def disconnect(self):
        """Disconnect from miniQMT platform."""
        try:
            if self.trader and self.is_connected:
                self.trader.stop()
                logger.info("Disconnected from miniQMT")
            self.is_connected = False
            self.is_subscribed = False
        except Exception as exc:
            logger.error("Disconnect error: %s", exc)

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    def __enter__(self):
        """Context manager entry."""
        if self.connect():
            return self
        _raise_broker_unavailable(
            account_id=self.config.account_id,
            error="connect() returned False; see logs above for error code and traceback",
        )

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.disconnect()

    # ------------------------------------------------------------------
    # Real-time data
    # ------------------------------------------------------------------

    def subscribe_tick(self, symbol: str) -> bool:
        """Subscribe to tick-level data for a futures symbol.

        Optional warm-up: get_full_tick() works without subscription,
        but subscribing ensures the local cache stays fresh during
        the wait period before order firing.

        Args:
            symbol: Contract code with suffix (e.g. 'al2605.SF').

        Returns:
            True if subscription successful or already active.
        """
        cache_key = f"{symbol}_tick"
        with self.subscription_lock:
            if cache_key in self.subscribed_symbols:
                return True

        try:
            result = xtdata.subscribe_quote(
                stock_code=symbol,
                period="tick",
                count=-1,
                start_time="",
                end_time="",
            )
            if result == 1:
                with self.subscription_lock:
                    self.subscribed_symbols.add(cache_key)
                logger.info("Tick subscription active: %s", symbol)
                return True
            else:
                logger.error("Tick subscription failed for %s: %s", symbol, result)
                return False
        except Exception as exc:
            logger.error("Tick subscription error for %s: %s", symbol, exc)
            return False

    def _get_tick_snapshot(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Read the latest tick snapshot via get_full_tick.

        Returns:
            Dict with askPrice (list[5]), bidPrice (list[5]),
            lastPrice, etc., or None.
        """
        try:
            data = xtdata.get_full_tick([symbol])
            if not data or symbol not in data:
                return None
            tick = data[symbol]
            if not isinstance(tick, dict) or not tick:
                return None
            return tick
        except Exception as exc:
            logger.warning("Tick snapshot failed for %s: %s", symbol, exc)
            return None

    def resolve_aggressive_price(
        self, symbol: str, intent: str,
    ) -> Tuple[int, float]:
        """Resolve price_type and price for aggressive (market-like) order.

        Returns FIX_PRICE with a price derived from live market data,
        or falls back to LATEST_PRICE as last resort.

        Tier 1: Counterparty price (ask1 for buy, bid1 for sell)
        Tier 2: Last traded price + 2-tick buffer
        Tier 3: LATEST_PRICE (let QMT resolve internally)

        Args:
            symbol: Contract code with suffix (e.g. 'al2605.SF').
            intent: Order intent ('ENTRY_LONG', 'EXIT_LONG', etc.).

        Returns:
            Tuple of (price_type constant, resolved price).
        """
        is_buy = intent in (
            "ENTRY_LONG", "EXIT_SHORT", "ROLLOVER_OPEN",
        )

        # Tier 1: counterparty price from order book
        tick = self._get_tick_snapshot(symbol)
        if tick is not None:
            if is_buy:
                ask_prices = tick.get("askPrice")
                if ask_prices is not None:
                    ask1 = ask_prices[0] if hasattr(ask_prices, '__getitem__') else 0
                    if ask1 and float(ask1) > 0:
                        price = float(ask1)
                        logger.info(
                            "Price resolved [Tier1 ask1]: %s %.2f",
                            symbol, price,
                        )
                        return xtconstant.FIX_PRICE, price
            else:
                bid_prices = tick.get("bidPrice")
                if bid_prices is not None:
                    bid1 = bid_prices[0] if hasattr(bid_prices, '__getitem__') else 0
                    if bid1 and float(bid1) > 0:
                        price = float(bid1)
                        logger.info(
                            "Price resolved [Tier1 bid1]: %s %.2f",
                            symbol, price,
                        )
                        return xtconstant.FIX_PRICE, price

            # Tier 2: lastPrice + buffer
            last_price = tick.get("lastPrice", 0)
            if last_price and float(last_price) > 0:
                last_price = float(last_price)
                detail = xtdata.get_instrument_detail(symbol)
                price_tick = float(detail.get("PriceTick", 5)) if detail else 5.0
                buffer = 2 * price_tick
                price = last_price + buffer if is_buy else last_price - buffer
                logger.info(
                    "Price resolved [Tier2 last+buffer]: %s %.2f "
                    "(last=%.2f, buffer=%.2f)",
                    symbol, price, last_price, buffer,
                )
                return xtconstant.FIX_PRICE, price

        # Tier 3: LATEST_PRICE — let QMT resolve internally.
        # This won't work on sim accounts but is acceptable: if we
        # reached here, tick data is empty/invalid and there's nothing
        # better to do.
        logger.warning(
            "Tier1/2 failed for %s — falling back to LATEST_PRICE",
            symbol,
        )
        return xtconstant.LATEST_PRICE, -1

    def download_main_contract_history(
        self, futures_code: str, xuntou_code: str,
    ) -> pd.DataFrame:
        """
        Download full main contract history via QMT's xtdata connection.

        Replicates the logic from SHFEApiMinuteExtractor._download_main_contract_history
        but uses the QMT desktop xtdata connection (no xtdc required).

        Args:
            futures_code: Futures product code (e.g. 'al').
            xuntou_code: Exchange code (e.g. 'SF').

        Returns:
            DataFrame with columns ``[date, main_contract]``.
        """
        symbol = f"{futures_code}00.{xuntou_code}"
        period = "historymaincontract"

        logger.info("Downloading main contract history for %s", symbol)

        xtdata.download_history_data(symbol, period, '', '')
        data_dict = xtdata.get_market_data_ex([], [symbol], period)

        if not data_dict or symbol not in data_dict:
            logger.warning("No main contract data for %s", symbol)
            return pd.DataFrame()

        df = data_dict[symbol].copy()

        # Convert timestamp to date
        df['date'] = pd.to_datetime(df['time'], unit='ms')
        df['date'] = df['date'].dt.strftime('%Y-%m-%d')

        # Rename Chinese column and filter
        df_filtered = df[['date', '期货统一规则代码']].copy()
        df_filtered.rename(
            columns={'期货统一规则代码': 'main_contract'}, inplace=True,
        )

        logger.info(
            "Main contract history downloaded: %d entries", len(df_filtered),
        )
        return df_filtered

    # ------------------------------------------------------------------
    # Order placement
    # ------------------------------------------------------------------

    def place_order(
        self,
        symbol: str,
        volume: int,
        price: Optional[float] = None,
        order_type: str = "LIMIT",
        intent: Optional[str] = None,
        scheduled_time: Optional[datetime.datetime] = None,
    ) -> Optional[int]:
        """
        Place a trading order with proper MiniQMT order type mapping.

        Execution timing depends on night market status:
        - If night market open and current time < 21:00 -> block until 21:00
          via dedicated thread + threading.Event.wait().
        - Otherwise execute immediately.

        Args:
            symbol: Trading symbol.
            volume: Number of contracts.
            price: Limit price (None for market order).
            order_type: 'LIMIT' or 'MARKET'.
            intent: One of 'ENTRY_LONG', 'ENTRY_SHORT', 'EXIT_LONG', 'EXIT_SHORT'.
            scheduled_time: Explicit execution time.  Auto-determined based on
                            night market status when None.

        Returns:
            Order ID if successful, None if failed.
        """
        if not self.is_connected or not self.is_subscribed:
            logger.error("Not connected to miniQMT or account not subscribed")
            return None

        try:
            # Check night market status for today
            shanghai_tz = pytz.timezone("Asia/Shanghai")
            now = datetime.datetime.now(shanghai_tz)
            night_market_open = is_night_market_open(self.market, self.asset, now)

            logger.info(
                "[place_order] Night market status: %s",
                "Open" if night_market_open else "Closed",
            )

            if night_market_open:
                # Night market is open - follow scheduler logic (21:00)
                logger.info(
                    "[place_order] Night market open - using scheduled execution"
                )

                if scheduled_time is None:
                    # Default to 21:00 today in Shanghai time
                    scheduled_time = now.replace(
                        hour=21, minute=0, second=0, microsecond=0
                    )

                if self._should_execute_immediately(scheduled_time):
                    logger.info(
                        "[place_order] Current time >= 21:00, executing immediately"
                    )
                    return self._execute_order_immediately(
                        symbol, volume, price, order_type, intent
                    )
                else:
                    logger.info(
                        "[place_order] Current time < 21:00, scheduling for %s",
                        scheduled_time,
                    )
                    logger.info(
                        "[place_order] Blocking execution: wait until scheduled time"
                    )
                    return self._schedule_order_blocking(
                        symbol, volume, price, order_type, intent, scheduled_time
                    )

            else:
                # Night market is closed - execute immediately
                logger.info(
                    "[place_order] Night market closed - executing immediately"
                )
                return self._execute_order_immediately(
                    symbol, volume, price, order_type, intent
                )

        except Exception as exc:
            logger.error("Error in place_order: %s", exc)
            logger.warning("Falling back to immediate execution due to error")
            return self._execute_order_immediately(
                symbol, volume, price, order_type, intent
            )

    def _execute_order_immediately(
        self,
        symbol: str,
        volume: int,
        price: Optional[float],
        order_type: str,
        intent: str,
    ) -> Optional[int]:
        """
        Execute order immediately using xtquant order_stock API.

        Maps intent strings to xtconstant futures order types:
        - ENTRY_LONG  -> xtconstant.FUTURE_OPEN_LONG
        - ENTRY_SHORT -> xtconstant.FUTURE_OPEN_SHORT
        - EXIT_LONG   -> xtconstant.FUTURE_CLOSE_LONG_HISTORY
        - EXIT_SHORT  -> xtconstant.FUTURE_CLOSE_SHORT_HISTORY

        Auto-appends .SF suffix for SHFE contracts when missing.
        """
        t_lock_wait = datetime.datetime.now()
        logger.info(
            "[DIAG] _execute_order_immediately: waiting for order_lock at %s",
            t_lock_wait.strftime("%H:%M:%S.%f"),
        )
        with self.order_lock:
            t_lock_acquired = datetime.datetime.now()
            logger.info(
                "[DIAG] _execute_order_immediately: order_lock ACQUIRED at %s "
                "(waited %.3fs)",
                t_lock_acquired.strftime("%H:%M:%S.%f"),
                (t_lock_acquired - t_lock_wait).total_seconds(),
            )
            # Set order parameters — use 3-tier aggressive pricing
            if order_type.upper() == "MARKET" or price is None:
                price_type, price = self.resolve_aggressive_price(symbol, intent)
            else:
                price_type = xtconstant.FIX_PRICE

            # Map intent to xtconstant order type
            intent_map = {
                "ENTRY_LONG": xtconstant.FUTURE_OPEN_LONG,
                "ENTRY_SHORT": xtconstant.FUTURE_OPEN_SHORT,
                "EXIT_LONG": xtconstant.FUTURE_CLOSE_LONG_HISTORY,
                "EXIT_SHORT": xtconstant.FUTURE_CLOSE_SHORT_HISTORY,
            }

            side = intent_map.get(intent)
            if side is None:
                logger.error("Unknown order intent: %s", intent)
                return None

            logger.info(
                "Placing %s order: %s x %d @ %s", intent, symbol, volume, price
            )
            logger.info(
                "Debug - Symbol format check: '%s' (length: %d)",
                symbol,
                len(symbol),
            )

            # Ensure proper exchange suffix for SHFE futures
            if not symbol.endswith(".SF"):
                # Check common SHFE product codes
                product_code = "".join(c for c in symbol if c.isalpha()).lower()
                shfe_products = {
                    "al", "cu", "zn", "pb", "ni", "sn", "au", "ag",
                    "rb", "hc", "ss", "bu", "ru", "fu", "sp", "nr",
                }
                if product_code in shfe_products:
                    logger.warning(
                        "Contract %s missing .SF suffix - adding it", symbol
                    )
                    symbol = symbol + ".SF"
                    logger.info("Corrected symbol: %s", symbol)

            logger.info(f'order_type is {side}, price_type is {price_type}, price is {price}')

            # Place order
            t_before_api = datetime.datetime.now()
            order_id = self.trader.order_stock(
                account=self.account,
                stock_code=symbol,
                order_type=side,
                order_volume=volume,
                price_type=price_type,
                price=price,
                strategy_name="DolphinQuantStrategy",
                order_remark=(
                    f"{intent}_{volume}_"
                    f"{datetime.datetime.now().strftime('%H%M%S')}"
                ),
            )
            t_after_api = datetime.datetime.now()
            logger.info(
                "[DIAG] order_stock API call took %.3fs",
                (t_after_api - t_before_api).total_seconds(),
            )

            if order_id > 0:
                order_info = OrderInfo(
                    order_id=order_id,
                    symbol=symbol,
                    intent=intent,
                    price=price,
                    volume=volume,
                    order_type=order_type,
                    timestamp=datetime.datetime.now(),
                )
                self.orders[order_id] = order_info
                logger.info("Order placed successfully: ID %s", order_id)
                return order_id
            else:
                logger.error(
                    "Failed to place order (code=%s): "
                    "account=%s, symbol=%s, side=%s, volume=%d, "
                    "price_type=%s, price=%s, connected=%s, subscribed=%s",
                    order_id,
                    self.config.account_id,
                    symbol,
                    intent,
                    volume,
                    price_type,
                    price,
                    self.is_connected,
                    self.is_subscribed,
                )
                return None

    def submit_order_async(
        self,
        symbol: str,
        volume: int,
        price: Optional[float],
        order_type: str,
        intent: str,
        strategy_name: str = "DolphinQuantStrategy",
    ) -> Optional[int]:
        """
        Submit order via xtquant order_stock_async (non-blocking).

        Unlike _execute_order_immediately which uses the synchronous
        order_stock (blocks until QMT confirms receipt), this method
        uses order_stock_async which returns a sequence ID immediately.
        The actual order_id arrives later via the order callback.

        Used by PortfolioTradingRunner for burst-fire: all orders hit
        QMT within ~50ms instead of sequentially waiting for each
        confirmation.

        Args:
            symbol: Contract code (e.g. 'al2508.SF')
            volume: Number of lots
            price: Limit price (None for market order)
            order_type: 'MARKET' or 'LIMIT'
            intent: 'ENTRY_LONG', 'ENTRY_SHORT', 'EXIT_LONG', 'EXIT_SHORT'
            strategy_name: Strategy name for QMT tracking

        Returns:
            Sequence ID (>0) on success, None on failure.
            The real order_id will arrive via order callback.
        """
        # Price type — use 3-tier aggressive pricing for market orders
        # LATEST_PRICE doesn't work on sim accounts and can fail at market
        # open when no last traded price exists. FIX_PRICE with resolved
        # counterparty/limit price works universally.
        if order_type.upper() == "MARKET" or price is None:
            price_type, price = self.resolve_aggressive_price(symbol, intent)
        else:
            price_type = xtconstant.FIX_PRICE

        # Map intent to xtconstant order type
        intent_map = {
            "ENTRY_LONG": xtconstant.FUTURE_OPEN_LONG,
            "ENTRY_SHORT": xtconstant.FUTURE_OPEN_SHORT,
            "EXIT_LONG": xtconstant.FUTURE_CLOSE_LONG_HISTORY,
            "EXIT_SHORT": xtconstant.FUTURE_CLOSE_SHORT_HISTORY,
            # "EXIT_LONG": xtconstant.FUTURE_CLOSE_LONG_TODAY,
            # "EXIT_SHORT": xtconstant.FUTURE_CLOSE_SHORT_TODAY,
            "FORCED_EXIT": xtconstant.FUTURE_CLOSE_LONG_HISTORY,
            "ROLLOVER_CLOSE": xtconstant.FUTURE_CLOSE_LONG_HISTORY,
            "ROLLOVER_OPEN": xtconstant.FUTURE_OPEN_LONG,
        }
        side = intent_map.get(intent)
        if side is None:
            logger.error("Unknown order intent: %s", intent)
            return None

        # Ensure .SF suffix for SHFE contracts
        if not symbol.endswith(".SF"):
            product_code = "".join(c for c in symbol if c.isalpha()).lower()
            shfe_products = {
                "al", "cu", "zn", "pb", "ni", "sn", "au", "ag",
                "rb", "hc", "ss", "bu", "ru", "fu", "sp", "nr",
            }
            if product_code in shfe_products:
                symbol = symbol + ".SF"
        print(f'debug: submit_order_async - symbol={symbol}, volume={volume}, price={price}, order_type={order_type}, intent={intent}, strategy_name={strategy_name}')
        try:
            seq_id = self.trader.order_stock_async(
                account=self.account,
                stock_code=symbol,
                order_type=side,
                order_volume=volume,
                price_type=price_type,
                price=price,
                strategy_name=strategy_name,
                order_remark=(
                    f"{intent}_{volume}_"
                    f"{datetime.datetime.now().strftime('%H%M%S')}"
                ),
            )
            logger.info(
                "Async order submitted: %s %s x %d, seq_id=%s",
                intent, symbol, volume, seq_id,
            )
            return seq_id if seq_id is not None and seq_id > 0 else None

        except Exception as exc:
            logger.error("order_stock_async failed: %s", exc)
            return None

    def _schedule_order_blocking(
        self,
        symbol: str,
        volume: int,
        price: Optional[float],
        order_type: str,
        intent: str,
        scheduled_time: datetime.datetime,
    ) -> Optional[int]:
        """
        Schedule order execution and wait for completion (blocking).

        Uses a dedicated daemon thread with ``time.sleep()`` to wait until
        ``scheduled_time``, then executes the order. This bypasses
        APScheduler's ``ThreadPoolExecutor`` which suffers GIL starvation
        when xtdc/xtdata C-extension threads hold the GIL at session open.

        ``time.sleep()`` fully releases the GIL, so the waiting thread is
        unaffected by C-extension contention. A spin-wait phase provides
        sub-10ms precision at execution time.

        Args:
            symbol: Trading symbol.
            volume: Number of contracts.
            price: Limit price.
            order_type: 'LIMIT' or 'MARKET'.
            intent: Order intent string.
            scheduled_time: When to execute.

        Returns:
            Order ID when the scheduled order fires, or None on failure.
        """
        completion_event = threading.Event()
        order_result: Dict[str, Optional[int]] = {"order_id": None}

        # Normalise to naive local timestamp for comparison with datetime.now()
        target = (
            scheduled_time.replace(tzinfo=None)
            if scheduled_time.tzinfo
            else scheduled_time
        )

        def _wait_and_execute():
            # Coarse sleep — releases GIL, won't be blocked by C-extensions
            while True:
                remaining = (target - datetime.datetime.now()).total_seconds()
                if remaining <= 1.0:
                    break
                time.sleep(min(remaining - 1.0, 30.0))

            # Spin-wait for sub-second precision
            while datetime.datetime.now() < target:
                time.sleep(0.005)

            # Diagnostic log
            t0 = datetime.datetime.now()
            delta = (t0 - target).total_seconds()
            logger.info(
                "[DIAG] _wait_and_execute FIRED at %s "
                "(target=%s, delta=%.3fs)",
                t0.strftime("%H:%M:%S.%f"),
                scheduled_time,
                delta,
            )

            try:
                oid = self._execute_order_immediately(
                    symbol, volume, price, order_type, intent
                )
                order_result["order_id"] = oid
            except Exception as exc:
                logger.error("Error in scheduled order execution: %s", exc)
            finally:
                completion_event.set()

        thread = threading.Thread(
            target=_wait_and_execute,
            name=f"OrderTimer_{symbol}_{intent}",
            daemon=True,
        )
        thread.start()

        logger.info(
            "Order scheduled via dedicated thread for %s (%s %s x%d)",
            scheduled_time,
            intent,
            symbol,
            volume,
        )

        # Block until the order executes
        completion_event.wait()

        logger.info(
            "Order execution completed, Order ID: %s",
            order_result["order_id"],
        )
        return order_result["order_id"]

    # APScheduler non-blocking path disabled — see _schedule_order_blocking
    # for the dedicated-thread replacement.
    #
    # def _schedule_order_non_blocking(
    #     self,
    #     symbol: str,
    #     volume: int,
    #     price: Optional[float],
    #     order_type: str,
    #     intent: str,
    #     scheduled_time: datetime.datetime,
    # ) -> Optional[str]:
    #     """
    #     Schedule order execution using APScheduler (non-blocking).
    #
    #     Returns the APScheduler job ID rather than an order ID.
    #     """
    #     if self.order_scheduler:
    #         job_id = (
    #             f"order_{symbol}_{intent}_"
    #             f"{datetime.datetime.now().strftime('%H%M%S%f')[:-3]}"
    #         )
    #
    #         self.order_scheduler.add_job(
    #             func=lambda: self._execute_order_immediately(
    #                 symbol, volume, price, order_type, intent
    #             ),
    #             trigger=DateTrigger(run_date=scheduled_time),
    #             id=job_id,
    #             name=f"Order_{symbol}_{intent}_{volume}",
    #             misfire_grace_time=60,
    #         )
    #
    #         logger.info(
    #             "Order scheduled for execution at %s, Job ID: %s",
    #             scheduled_time,
    #             job_id,
    #         )
    #         return job_id
    #     else:
    #         logger.error("Order scheduler not available, executing immediately")
    #         return self._execute_order_immediately(
    #             symbol, volume, price, order_type, intent
    #         )

    # ------------------------------------------------------------------
    # Order management
    # ------------------------------------------------------------------

    def cancel_order(self, order_id: int) -> bool:
        """
        Cancel a pending order.

        Args:
            order_id: Order ID to cancel.

        Returns:
            True if cancellation successful.
        """
        if not self.is_connected:
            logger.error("Not connected to miniQMT")
            return False

        try:
            result = self.trader.cancel_order_stock(self.account, order_id)
            if result == 0:
                logger.info("Order %s cancelled successfully", order_id)

                if order_id in self.orders:
                    self.orders[order_id].status = "CANCELLED"

                return True
            else:
                logger.error("Failed to cancel order %s: %s", order_id, result)
                return False

        except Exception as exc:
            logger.error("Order cancellation error: %s", exc)
            return False

    def query_stock_trades(self) -> List[Dict[str, Any]]:
        """
        Query all stock trades for the account.

        Returns:
            List of trade dictionaries with trade execution details.
        """
        if not self.is_connected:
            logger.error("Not connected to miniQMT")
            return []

        try:
            logger.info("Querying stock trades...")

            trades = None
            if hasattr(self.trader, "query_stock_trades"):
                trades = self.trader.query_stock_trades(self.account)
                logger.info("query_stock_trades returned: %s", trades)

            if hasattr(self.trader, "query_history_trades"):
                try:
                    hist_trades = self.trader.query_history_trades(self.account)
                    logger.info("query_history_trades returned: %s", hist_trades)
                    if hist_trades and not trades:
                        trades = hist_trades
                except Exception as hist_exc:
                    logger.warning(
                        "query_history_trades failed: %s", hist_exc
                    )

            if not trades:
                logger.info("No trades found with any query method")
                return []

            trade_list = []
            for trade in trades:
                try:
                    trade_dict = {
                        "order_id": getattr(trade, "order_id", "N/A"),
                        "stock_code": getattr(trade, "stock_code", "N/A"),
                        "order_type": getattr(trade, "order_type", "N/A"),
                        "traded_id": getattr(trade, "traded_id", ""),
                        "traded_time": getattr(trade, "traded_time", ""),
                        "traded_price": getattr(trade, "traded_price", 0.0),
                        "traded_volume": getattr(trade, "traded_volume", 0),
                        "traded_amount": getattr(trade, "traded_amount", 0.0),
                        "strategy_name": getattr(trade, "strategy_name", ""),
                        "order_remark": getattr(trade, "order_remark", ""),
                    }
                    trade_list.append(trade_dict)
                except Exception as parse_exc:
                    logger.error("Error parsing trade: %s", parse_exc)
                    logger.error("Trade object: %s", trade)
                    logger.error("Trade attributes: %s", dir(trade))

            logger.info("Found %d trades", len(trade_list))
            return trade_list

        except Exception as exc:
            logger.error("Failed to query stock trades: %s", exc)
            logger.error("Full traceback: %s", traceback.format_exc())
            return []

    # ------------------------------------------------------------------
    # Positions & account
    # ------------------------------------------------------------------

    def get_positions(self) -> Dict[str, PositionInfo]:
        """
        Get current positions via trader.query_position_statistics.

        Direction codes from xtquant:
        - 48 = LONG
        - 49 = SHORT

        Returns:
            Dictionary of PositionInfo keyed by symbol.
        """
        if not self.is_connected:
            logger.error("Not connected to miniQMT")
            return {}

        positions = self.trader.query_position_statistics(self.account)

        position_dict: Dict[str, PositionInfo] = {}

        for pos in positions:
            if hasattr(pos, "instrument_id"):
                symbol = getattr(pos, "instrument_id")
                volume = getattr(pos, "position")
                avg_price = getattr(pos, "avg_price")
                unrealized_pnl = getattr(pos, "float_profit")
                market_value = getattr(pos, "instrument_value")
                direction_code = getattr(pos, "direction")

                if direction_code == 48:
                    direction = "LONG"
                elif direction_code == 49:
                    direction = "SHORT"
                else:
                    direction = f"UNKNOWN_{direction_code}"

                logger.info(
                    "Found position: %s, volume: %s, avg_price: %s",
                    symbol,
                    volume,
                    avg_price,
                )

                # Skip positions with zero volume
                if volume == 0:
                    logger.info("Skipping zero-volume position: %s", symbol)
                    continue

                position_info = PositionInfo(
                    symbol=symbol,
                    volume=volume,
                    avg_price=avg_price,
                    unrealized_pnl=unrealized_pnl,
                    market_value=market_value,
                    direction=direction,
                )

                position_dict[symbol] = position_info

        with self.data_lock:
            self.positions = position_dict

        return position_dict

    def get_account_info(self) -> Optional[Dict[str, Any]]:
        """
        Get account information via trader.query_stock_asset.

        Returns:
            Dictionary with account_id, cash, total_asset,
            market_value, frozen_cash, available_cash.
        """
        if not self.is_connected:
            logger.error("Not connected to miniQMT")
            return None

        try:
            account_info = self.trader.query_stock_asset(self.account)

            return {
                "account_id": self.config.account_id,
                "cash": account_info.m_dCash,
                "total_asset": account_info.m_dTotalAsset,
                "market_value": account_info.m_dMarketValue,
                "frozen_cash": account_info.m_dFrozenCash,
                "available_cash": account_info.m_dCash,
            }

        except Exception as exc:
            logger.error("Failed to get account info: %s", exc)
            return None

    # ------------------------------------------------------------------
    # Callbacks
    # ------------------------------------------------------------------

    def set_callbacks(
        self,
        order_callback: Optional[Callable] = None,
        trade_callback: Optional[Callable] = None,
        market_data_callback: Optional[Callable] = None,
        async_response_callback: Optional[Callable] = None,
    ):
        """Set callback functions for order, trade, and market data events."""
        self.order_callback = order_callback
        self.trade_callback = trade_callback
        self.market_data_callback = market_data_callback
        self.async_response_callback = async_response_callback

