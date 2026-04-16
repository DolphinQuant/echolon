"""
Trading Context - Runtime context for market-specific trading operations.

TradingContext encapsulates all market, instrument, and frequency information
needed by trading modules. It's created by MarketFactory from session state
and passed to modules via dependency injection.

Usage:
    from config.markets.factory import MarketFactory

    # Create context from session state
    ctx = MarketFactory.from_session()

    # Use in modules
    commission = ctx.instrument.calculate_commission(price, size)
    phase = ctx.encode_phase("morning")
    bars = ctx.bars_per_day
"""

from dataclasses import dataclass, field
from datetime import time, datetime
from typing import Dict, List, Optional, Callable

# Import types at runtime (required for Pydantic models that use TradingContext)
from .types import MarketConfig, InstrumentSpec, SessionWindow, SessionPhaseSpec
from .trading_target import TradingTarget


@dataclass
class TradingContext:
    """
    Runtime trading context for a specific market/instrument/frequency combination.

    This is the primary interface for modules to access market configuration.
    Created by MarketFactory and passed to modules that need market info.

    Attributes:
        market: Market configuration (SHFE, CRYPTO, etc.)
        instrument: Instrument specification (al, btc, etc.)
        frequency: Trading frequency ('intraday' or 'interday')
        bar_size: Bar size string ('5m', '15m', '1d', etc.)
        target: User's trading target (TradingTarget from state.json)
    """
    market: MarketConfig
    instrument: InstrumentSpec
    frequency: str  # 'intraday' | 'interday'
    bar_size: str   # '1m', '5m', '15m', '30m', '1h', '1d'

    # User's trading target (TradingTarget from session/state.json)
    target: Optional[TradingTarget] = field(default=None, repr=False)

    # Encoding functions (set by factory based on market)
    _encode_phase: Callable[[str], int] = field(default=lambda x: 0, repr=False)
    _decode_phase: Callable[[int], str] = field(default=lambda x: 'unknown', repr=False)

    # =========================================================================
    # Market Properties
    # =========================================================================

    @property
    def market_code(self) -> str:
        """Market code (e.g., 'SHFE', 'CRYPTO')."""
        return self.market.code

    @property
    def timezone(self) -> str:
        """Market timezone (e.g., 'Asia/Shanghai', 'UTC')."""
        return self.market.timezone

    @property
    def currency(self) -> str:
        """Trading currency (e.g., 'CNY', 'USDT')."""
        return self.market.currency

    @property
    def is_24h(self) -> bool:
        """Whether market trades 24/7 (crypto)."""
        return self.market.is_24h

    @property
    def has_contract_expiry(self) -> bool:
        """Whether contracts expire (futures vs perpetuals)."""
        return self.market.has_contract_expiry

    # =========================================================================
    # Instrument Properties
    # =========================================================================

    @property
    def instrument_code(self) -> str:
        """Instrument code (e.g., 'al', 'btc')."""
        return self.instrument.code

    @property
    def instrument_name(self) -> str:
        """Instrument name (e.g., 'Aluminum', 'Bitcoin Perpetual')."""
        return self.instrument.name

    @property
    def multiplier(self) -> float:
        """Contract multiplier."""
        return self.instrument.multiplier

    @property
    def tick_size(self) -> float:
        """Minimum price movement."""
        return self.instrument.tick_size

    @property
    def margin_rate(self) -> float:
        """Margin requirement (decimal, e.g., 0.08 = 8%)."""
        return self.instrument.margin_rate

    @property
    def has_night_session(self) -> bool:
        """Whether instrument trades in night session."""
        return self.instrument.has_night_session

    @property
    def initial_capital(self) -> float:
        """Initial capital for backtesting and live trading."""
        if self.target:
            return self.target.initial_capital
        return 200000.0

    # =========================================================================
    # Session Access
    # =========================================================================

    @property
    def sessions(self) -> Dict[str, SessionWindow]:
        """All session windows for this market."""
        return self.market.sessions

    @property
    def phases(self) -> Dict[str, SessionPhaseSpec]:
        """All session phases for this market."""
        return self.market.phases

    @property
    def trading_phases(self) -> List[SessionPhaseSpec]:
        """Only trading phases (excludes breaks)."""
        return [p for p in self.market.phases.values() if p.is_trading]

    # =========================================================================
    # Frequency Properties
    # =========================================================================

    @property
    def is_intraday(self) -> bool:
        """Whether trading intraday."""
        return self.frequency == 'intraday'

    @property
    def is_interday(self) -> bool:
        """Whether trading interday (daily bars)."""
        return self.frequency == 'interday'

    @property
    def bars_per_day(self) -> int:
        """Expected bars per trading day."""
        if self.is_interday:
            return 1

        # Get from market-specific constants
        if self.market_code == 'SHFE':
            from config.markets.shfe.constants import BARS_PER_DAY, BARS_PER_DAY_NO_NIGHT
            bars_map = BARS_PER_DAY if self.has_night_session else BARS_PER_DAY_NO_NIGHT
            return bars_map.get(self.bar_size)
        elif self.market_code == 'CRYPTO':
            from config.markets.crypto.perpetuals import BARS_PER_DAY
            return BARS_PER_DAY.get(self.bar_size, 288)

        return 1  # Default for unknown markets

    @property
    def trading_minutes_per_day(self) -> int:
        """Total trading minutes per day."""
        if self.market_code == 'SHFE':
            from config.markets.shfe.constants import TOTAL_TRADING_MINUTES, DAY_TRADING_MINUTES
            return TOTAL_TRADING_MINUTES if self.has_night_session else DAY_TRADING_MINUTES
        elif self.market_code == 'CRYPTO':
            return 24 * 60  # 1440 minutes

        return 24 * 60  # Default

    # =========================================================================
    # Frequency-Derived Parameters (for Indicators)
    # =========================================================================

    @property
    def bar_size_minutes(self) -> int:
        """
        Bar size in minutes.

        Parses bar_size string ('1m', '5m', '15m', '30m', '1h', '4h', '1d')
        and returns the duration in minutes.
        """
        bar_size_lower = self.bar_size.lower()

        # Handle hour format
        if 'h' in bar_size_lower:
            hours = int(bar_size_lower.replace('h', ''))
            return hours * 60

        # Handle minute formats (both "5m" and "5min")
        if 'min' in bar_size_lower:
            return int(bar_size_lower.replace('min', ''))
        if 'm' in bar_size_lower:
            return int(bar_size_lower.replace('m', ''))

        # Handle day format
        if 'd' in bar_size_lower:
            return 1440  # 24 * 60


    @property
    def bars_per_hour(self) -> int:
        """Bars per hour for current frequency."""
        if self.bar_size_minutes >= 60:
            return 1
        return 60 // self.bar_size_minutes

    def hours_to_bars(self, hours: float) -> int:
        """
        Convert hours to bar count for current frequency.

        Args:
            hours: Duration in hours

        Returns:
            Number of bars (minimum 1)
        """
        return max(1, int(hours * self.bars_per_hour))

    def minutes_to_bars(self, minutes: int) -> int:
        """
        Convert minutes to bar count for current frequency.

        Args:
            minutes: Duration in minutes

        Returns:
            Number of bars (minimum 1)
        """
        return max(1, minutes // self.bar_size_minutes)

    def get_indicator_params(self) -> dict:
        """
        Get frequency-appropriate indicator parameters.

        For INTERDAY (daily bars): Returns standard TA-Lib defaults
        For INTRADAY: Returns time-scaled parameters based on bar_size

        Returns:
            Dictionary of indicator parameters appropriate for current frequency
        """
        # INTERDAY: Use standard TA-Lib defaults (industry standard for daily bars)
        if self.is_interday:
            return {
                # Momentum indicators (standard daily defaults)
                "rsi_period": 14,
                "cci_period": 20,
                "willr_period": 14,
                "mfi_period": 14,
                "mom_period": 10,

                # Trend indicators
                "adx_period": 14,
                "aroonosc_period": 25,

                # Volatility
                "atr_period": 14,

                # Moving averages
                "ema_fast": 12,
                "ema_slow": 26,
                "sma_short": 20,
                "sma_mid": 50,

                # MACD (standard 12/26/9)
                "macd_fast": 12,
                "macd_slow": 26,
                "macd_signal": 9,

                # Bollinger Bands
                "bb_period": 20,

                # Volume percentile (20 trading days)
                "vol_lookback": 20,

                # Opening range (not applicable for daily)
                "or_bars": 1,
                "or_minutes": 0,

                # Channel periods (5, 10, 20 days)
                "channel_periods": [5, 10, 20],

                # ROC periods (5, 10, 20 days)
                "roc_periods": [5, 10, 20],

                # Volatility state
                "volatility_atr_period": 14,
                "volatility_lookback": 60,
                "volatility_high_pct": 75.0,
                "volatility_low_pct": 25.0,
            }

        # INTRADAY: Scale parameters based on bar_size to maintain consistent
        # lookback periods in real time across different bar sizes
        return {
            # Momentum indicators (~2-3 hours lookback)
            "rsi_period": self.hours_to_bars(2.3),
            "cci_period": self.hours_to_bars(3.3),
            "willr_period": self.hours_to_bars(2.3),
            "mfi_period": self.hours_to_bars(2.3),
            "mom_period": self.hours_to_bars(1.0),

            # Trend indicators (~2-3 hours)
            "adx_period": self.hours_to_bars(2.3),
            "aroonosc_period": self.hours_to_bars(3.3),

            # Volatility
            "atr_period": self.hours_to_bars(2.3),

            # Moving averages
            "ema_fast": self.hours_to_bars(1.0),
            "ema_slow": self.hours_to_bars(2.3),
            "sma_short": self.hours_to_bars(1.5),
            "sma_mid": self.hours_to_bars(3.3),

            # MACD (scaled)
            "macd_fast": max(3, self.minutes_to_bars(25)),
            "macd_slow": max(7, self.minutes_to_bars(65)),
            "macd_signal": max(3, self.minutes_to_bars(25)),

            # Bollinger Bands
            "bb_period": self.hours_to_bars(1.5),

            # Volume percentile (1 trading day)
            "vol_lookback": self.bars_per_day,

            # Opening range (30 minutes)
            "or_bars": self.minutes_to_bars(30),
            "or_minutes": 30,

            # Channel periods (1h, 2h, 4h)
            "channel_periods": [
                self.hours_to_bars(1),
                self.hours_to_bars(2),
                self.hours_to_bars(4),
            ],

            # ROC periods (30m, 1h, 2h)
            "roc_periods": [
                self.minutes_to_bars(30),
                self.hours_to_bars(1),
                self.hours_to_bars(2),
            ],

            # Volatility state
            "volatility_atr_period": self.hours_to_bars(1.2),
            "volatility_lookback": self.bars_per_day,
            "volatility_high_pct": 75.0,
            "volatility_low_pct": 25.0,
        }

    def get_session_bars(self, session_phase: str) -> int:
        """
        Get expected bars for a session phase.

        Args:
            session_phase: 'night', 'morning', 'afternoon', 'day1', 'day2'

        Returns:
            Expected number of bars in that session
        """
        if self.market_code == 'SHFE':
            from config.markets.shfe.constants import get_session_bars
            return get_session_bars(self.bar_size, session_phase, self.has_night_session)
        elif self.market_code == 'CRYPTO':
            # Crypto has 24h continuous - divide by 3 for "sessions"
            return self.bars_per_day // 3

        return self.bars_per_day

    # =========================================================================
    # Phase Encoding (for Backtrader compatibility)
    # =========================================================================

    def encode_phase(self, phase_str: str) -> int:
        """
        Convert session phase string to numeric encoding.

        This method is bar_size-aware (bar_size baked in at context creation):
        - Granular (5m/15m): 'night'->1, 'morning'->2, 'afternoon'->5
        - Aggregated (30m/1h): 'night_session'->1, 'day_session'->2

        Args:
            phase_str: Phase name. For granular bars: 'night', 'morning', 'afternoon'.
                      For aggregated bars: 'night_session', 'day_session'.

        Returns:
            Numeric encoding for Backtrader data feed (0 if unknown)
        """
        return self._encode_phase(phase_str)

    def decode_phase(self, phase_code: int) -> str:
        """
        Convert numeric phase code to string.

        This method is bar_size-aware (bar_size baked in at context creation):
        - Granular (5m/15m): 1->'night', 2->'morning', 5->'afternoon'
        - Aggregated (30m/1h): 1->'night_session', 2->'day_session'

        Args:
            phase_code: Numeric encoding from Backtrader data feed

        Returns:
            Phase name string ('unknown' if code not recognized)
        """
        return self._decode_phase(phase_code)

    def get_phase_for_time(self, t: time) -> Optional[str]:
        """
        Get session phase name for a given time.

        Args:
            t: Time to check

        Returns:
            Phase name or None if outside trading hours
        """
        for name, phase in self.phases.items():
            if phase.contains_time(t):
                return name
        return None

    def is_trading_time(self, t: time) -> bool:
        """
        Check if time is during active trading (not in a break).

        Args:
            t: Time to check

        Returns:
            True if during trading hours
        """
        phase_name = self.get_phase_for_time(t)
        if phase_name is None:
            return False
        return self.phases[phase_name].is_trading

    # =========================================================================
    # Calculations
    # =========================================================================

    def calculate_commission(self, price: float, size: int) -> float:
        """Calculate commission for a trade."""
        return self.instrument.calculate_commission(price, size)

    def calculate_margin(self, price: float, size: int) -> float:
        """Calculate required margin."""
        return self.instrument.calculate_margin(price, size)

    def calculate_contract_value(self, price: float, size: int) -> float:
        """Calculate total contract value."""
        return self.instrument.calculate_contract_value(price, size)

    # =========================================================================
    # Serialization
    # =========================================================================

    def to_dict(self) -> dict:
        """Convert to dictionary for logging/serialization."""
        return {
            'market': self.market_code,
            'instrument': self.instrument_code,
            'instrument_name': self.instrument_name,
            'frequency': self.frequency,
            'bar_size': self.bar_size,
            'timezone': self.timezone,
            'currency': self.currency,
            'multiplier': self.multiplier,
            'tick_size': self.tick_size,
            'margin_rate': self.margin_rate,
            'has_night_session': self.has_night_session,
            'is_24h': self.is_24h,
            'bars_per_day': self.bars_per_day,
            'initial_capital': self.initial_capital,
        }

    def __repr__(self) -> str:
        return (
            f"TradingContext("
            f"market={self.market_code}, "
            f"instrument={self.instrument_code}, "
            f"frequency={self.frequency}, "
            f"bar_size={self.bar_size})"
        )

    # =========================================================================
    # Bar-Size-Aware Phase Selection (SHFE-specific)
    # =========================================================================

    @property
    def is_aggregated_phases(self) -> bool:
        """
        Whether current bar size uses aggregated session phases.

        Returns:
            True for 30m/1h bars (uses night_session, day_session)
            False for 5m/15m bars (uses night, morning, afternoon)
        """
        if self.market_code == 'SHFE' and self.is_intraday:
            from config.markets.shfe.phases import is_aggregated_bar_size
            return is_aggregated_bar_size(self.bar_size)
        return False

    @property
    def tradeable_phases(self) -> List[str]:
        """
        Get list of tradeable phase names appropriate for current bar size.

        Returns:
            ['night', 'morning', 'afternoon'] for 5m/15m
            ['night_session', 'day_session'] for 30m/1h
        """
        if self.market_code == 'SHFE' and self.is_intraday:
            from config.markets.shfe.phases import get_tradeable_phases
            return get_tradeable_phases(self.bar_size)
        # Default: return all trading phase names
        return [p.name for p in self.trading_phases]

    def get_phase_bars(self, phase: str) -> int:
        """
        Get expected bars for a session phase, bar-size-aware.

        Args:
            phase: Phase name (granular or aggregated)

        Returns:
            Expected number of bars in that phase
        """
        if self.market_code == 'SHFE':
            from config.markets.shfe.phases import get_phase_trading_bars
            return get_phase_trading_bars(
                phase, self.bar_size_minutes, bar_size=self.bar_size
            )
        return self.bars_per_day

    def get_phase_buffer_bars(self, phase: str, buffer_type: str) -> int:
        """
        Get buffer bars for a phase (opening or closing), bar-size-aware.

        Args:
            phase: Phase name (granular or aggregated)
            buffer_type: 'opening' or 'closing'

        Returns:
            Number of buffer bars
        """
        if self.market_code == 'SHFE':
            from config.markets.shfe.phases import get_phase_buffer_bars
            return get_phase_buffer_bars(
                phase, buffer_type, self.bar_size_minutes, bar_size=self.bar_size
            )
        return 0

    def get_phase_for_time_bar_aware(self, t: time) -> Optional[str]:
        """
        Get session phase name for a given time, bar-size-aware.

        Args:
            t: Time to check

        Returns:
            Phase name appropriate for current bar size, or None
        """
        if self.market_code == 'SHFE':
            from config.markets.shfe.phases import get_phase_for_time
            return get_phase_for_time(t, bar_size=self.bar_size)
        return self.get_phase_for_time(t)

    @property
    def design_paradigm_description(self) -> str:
        """
        Get human-readable description of the design paradigm.

        Returns:
            Description of granular vs aggregated session design
        """
        if self.market_code == 'SHFE' and self.is_intraday:
            from config.markets.shfe.phases import get_design_paradigm_description
            return get_design_paradigm_description(self.bar_size)
        return "Standard session-based design"
