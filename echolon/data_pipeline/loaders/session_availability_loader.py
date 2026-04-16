"""
Session Availability Loader
============================

Loads session availability data for accurate bar counting in intraday trading.

This module provides access to actual session availability per trading date,
which is critical for:
- Accurate bar_of_day / bars_remaining calculations
- Detecting trading days without night sessions (post-holiday)
- Session-specific bar counts

Important: The session_availability.csv stores 1-minute bar counts summed across
ALL contracts (not per-contract). For indicator calculations, use methods that
return expected bar counts per bar_size (e.g., get_expected_total_bars).

Data Source: workspace/data/market_data/{market}/{instrument}/session_availability.csv
"""

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional

import pandas as pd

from echolon.config.settings import MARKET_DATA_DIR
from echolon.config.markets.shfe.phases import (
    get_phase_trading_bars,
    get_tradeable_phases,
    is_aggregated_bar_size,
)

logger = logging.getLogger(__name__)


@dataclass
class SessionDayInfo:
    """
    Session availability information for a single trading date.

    Supports both granular phases (night, morning, afternoon) and
    aggregated phases (night_session, day_session) depending on bar_size.

    Attributes:
        trading_date: Trading date in YYYYMMDD format
        phase_availability: Dict mapping phase_name -> bool (has session)
        phase_bars: Dict mapping phase_name -> int (bar count)
        total_bars: Total bars for the trading day
        tradeable_phases: List of phase names for this schema
    """
    trading_date: str
    phase_availability: Dict[str, bool]
    phase_bars: Dict[str, int]
    total_bars: int
    tradeable_phases: list

    # Backward compatibility properties for granular phases
    @property
    def has_night(self) -> bool:
        """Whether night session exists (granular or aggregated)."""
        return self.phase_availability.get('night', False) or \
               self.phase_availability.get('night_session', False)

    @property
    def has_morning(self) -> bool:
        """Whether morning session exists (granular only)."""
        return self.phase_availability.get('morning', False)

    @property
    def has_afternoon(self) -> bool:
        """Whether afternoon session exists (granular only)."""
        return self.phase_availability.get('afternoon', False)

    @property
    def has_day_session(self) -> bool:
        """Whether day session exists (aggregated only)."""
        return self.phase_availability.get('day_session', False)

    @property
    def has_night_session(self) -> bool:
        """Whether night session exists (aggregated only)."""
        return self.phase_availability.get('night_session', False)

    @property
    def night_bars(self) -> int:
        """Bar count in night session (granular or aggregated)."""
        return self.phase_bars.get('night', 0) or \
               self.phase_bars.get('night_session', 0)

    @property
    def morning_bars(self) -> int:
        """Bar count in morning session (granular only)."""
        return self.phase_bars.get('morning', 0)

    @property
    def afternoon_bars(self) -> int:
        """Bar count in afternoon session (granular only)."""
        return self.phase_bars.get('afternoon', 0)

    @property
    def day_session_bars(self) -> int:
        """Bar count in day session (aggregated only)."""
        return self.phase_bars.get('day_session', 0)

    @property
    def night_session_bars(self) -> int:
        """Bar count in night session (aggregated only)."""
        return self.phase_bars.get('night_session', 0)

    @property
    def sessions_active(self) -> list:
        """Get list of active session names."""
        return [phase for phase in self.tradeable_phases
                if self.phase_availability.get(phase, False)]

    def get_session_bars(self, session_phase: str) -> int:
        """Get bar count for a specific session phase."""
        return self.phase_bars.get(session_phase, 0)

    def has_session(self, session_phase: str) -> bool:
        """Check if a specific session phase is available."""
        return self.phase_availability.get(session_phase, False)


class SessionAvailabilityLoader:
    """
    Loads and provides access to session availability data.

    Supports both granular phases (night, morning, afternoon) for 5m/15m bars
    and aggregated phases (night_session, day_session) for 30m/1h bars.

    Important: The session_availability.csv stores bar counts per phase.
    The schema depends on how the data was generated (bar_size used during analysis).

    Usage:
        # For granular phases (5m, 15m)
        loader = SessionAvailabilityLoader('SHFE', 'aluminum', bar_size_minutes=5)

        # For aggregated phases (30m, 1h)
        loader = SessionAvailabilityLoader('SHFE', 'aluminum', bar_size_minutes=30, bar_size='30m')

        # Check if a trading date has night session
        if loader.has_night_session('20251009'):
            ...

        # Get expected bars for a trading date (accounts for session availability)
        total = loader.get_expected_total_bars('20251009')

        # Get expected bars for a specific session
        night_bars = loader.get_expected_session_bars('20251009', 'night')  # 0 if no night

        # Get full session info
        info = loader.get_session_info('20251009')
        print(info.has_night)  # False
    """

    def __init__(
        self,
        market: str,
        instrument: str,
        bar_size_minutes: int,
        bar_size: Optional[str] = None
    ):
        """
        Initialize loader.

        Args:
            market: Market code (e.g., 'SHFE')
            instrument: Instrument name (e.g., 'aluminum')
            bar_size_minutes: Bar size in minutes for expected bar calculations (required)
            bar_size: Optional bar size string ('5m', '15m', '30m', '1h').
                      For 30m/1h, uses aggregated phases (night_session, day_session).
                      For 5m/15m or None, uses granular phases (night, morning, afternoon).
        """
        self.market = market.upper()
        self.instrument = instrument
        self.bar_size_minutes = bar_size_minutes
        self.bar_size = bar_size
        self._data: Dict[str, SessionDayInfo] = {}
        self._loaded = False

        # Get tradeable phases based on bar_size
        self.tradeable_phases = get_tradeable_phases(bar_size)
        self.is_aggregated = is_aggregated_bar_size(bar_size) if bar_size else False

        # Pre-calculate expected bars per session (from SHFE phase config)
        self._expected_bars = {
            phase: get_phase_trading_bars(phase, bar_size_minutes, bar_size=bar_size)
            for phase in self.tradeable_phases
        }

        # Calculate total expected bars (full day vs day-only)
        self._expected_full_day_bars = sum(self._expected_bars.values())

        # For day-only, exclude night/night_session
        night_phase = 'night_session' if self.is_aggregated else 'night'
        self._expected_day_only_bars = (
            self._expected_full_day_bars - self._expected_bars.get(night_phase, 0)
        )

        # Backward compatibility properties for granular phases
        self._expected_night_bars = self._expected_bars.get('night', 0) or \
                                     self._expected_bars.get('night_session', 0)
        self._expected_morning_bars = self._expected_bars.get('morning', 0)
        self._expected_afternoon_bars = self._expected_bars.get('afternoon', 0)
        self._expected_day_session_bars = self._expected_bars.get('day_session', 0)
        self._expected_night_session_bars = self._expected_bars.get('night_session', 0)

        # Load data
        self._load()

    def _load(self) -> None:
        """Load session availability data from CSV."""
        file_path = MARKET_DATA_DIR / self.market / self.instrument / "session_availability.csv"

        if not file_path.exists():
            logger.warning(
                f"[SESSION_AVAILABILITY] File not found: {file_path}. "
                f"Bar counts will use default values."
            )
            return

        try:
            df = pd.read_csv(file_path)

            # Detect CSV schema (granular vs aggregated)
            has_granular = 'has_night' in df.columns
            has_aggregated = 'has_night_session' in df.columns

            # Determine phases to load based on CSV schema
            if has_aggregated:
                csv_phases = ['night_session', 'day_session']
            elif has_granular:
                csv_phases = ['night', 'morning', 'afternoon']
            else:
                logger.warning("[SESSION_AVAILABILITY] Unknown CSV schema, using expected phases")
                csv_phases = self.tradeable_phases

            for _, row in df.iterrows():
                trading_date = str(row['trading_date'])

                # Build phase availability and bar counts dynamically
                phase_availability = {}
                phase_bars = {}

                for phase in csv_phases:
                    has_col = f'has_{phase}'
                    bars_col = f'{phase}_bars'
                    phase_availability[phase] = bool(row.get(has_col, True))
                    phase_bars[phase] = int(row.get(bars_col, 0))

                info = SessionDayInfo(
                    trading_date=trading_date,
                    phase_availability=phase_availability,
                    phase_bars=phase_bars,
                    total_bars=int(row.get('total_bars', 0)),
                    tradeable_phases=csv_phases,
                )
                self._data[trading_date] = info

            self._loaded = True
            schema_type = "aggregated" if has_aggregated else "granular"
            logger.info(
                f"[SESSION_AVAILABILITY] Loaded {len(self._data)} trading dates "
                f"for {self.market}/{self.instrument} ({schema_type} schema)"
            )

        except Exception as e:
            logger.error(f"[SESSION_AVAILABILITY] Failed to load: {e}")

    @property
    def is_loaded(self) -> bool:
        """Check if data was successfully loaded."""
        return self._loaded

    def get_session_info(self, trading_date: str) -> Optional[SessionDayInfo]:
        """
        Get session info for a trading date.

        Args:
            trading_date: Trading date in YYYYMMDD format

        Returns:
            SessionDayInfo or None if not found
        """
        # Normalize format
        trading_date = str(trading_date).replace('-', '')
        return self._data.get(trading_date)

    def has_night_session(self, trading_date: str) -> bool:
        """
        Check if a trading date has night session.

        Args:
            trading_date: Trading date in YYYYMMDD format

        Returns:
            True if night session exists, False otherwise.
            Returns True (default) if trading_date not found.
        """
        info = self.get_session_info(trading_date)
        if info is None:
            return True  # Default assumption
        return info.has_night

    def get_total_bars(self, trading_date: str) -> int:
        """
        Get total bars for a trading date.

        Args:
            trading_date: Trading date in YYYYMMDD format
        Returns:
            Total bar count for the trading day
        """
        info = self.get_session_info(trading_date)
        return info.total_bars

    def get_session_bars(
        self,
        trading_date: str,
        session_phase: str,
    ) -> int:
        """
        Get bar count for a specific session on a trading date.

        Args:
            trading_date: Trading date in YYYYMMDD format
            session_phase: Session phase ('night', 'morning', 'afternoon')

        Returns:
            Bar count for the session
        """
        info = self.get_session_info(trading_date)
        return info.get_session_bars(session_phase)

    def get_trading_dates(self) -> list:
        """Get list of all trading dates in the data."""
        return list(self._data.keys())

    def get_dates_without_night(self) -> list:
        """Get list of trading dates that don't have night session."""
        return [
            td for td, info in self._data.items()
            if not info.has_night
        ]

    # =========================================================================
    # Expected Bar Count Methods (for indicator calculations)
    # =========================================================================

    def get_expected_total_bars(self, trading_date: str) -> int:
        """
        Get expected total bars for a trading date based on session availability.

        Uses SHFE phase definitions (PHASE_TRADING_MINUTES) and bar_size_minutes
        to calculate expected bar count, accounting for whether night session exists.

        Args:
            trading_date: Trading date in YYYYMMDD format

        Returns:
            Expected bar count for the trading day (computed from bar_size_minutes):
            - Full day with night: night_bars + morning_bars + afternoon_bars
            - Day without night: morning_bars + afternoon_bars
        """
        if self.has_night_session(trading_date):
            return self._expected_full_day_bars
        return self._expected_day_only_bars

    def get_expected_session_bars(self, trading_date: str, session_phase: str) -> int:
        """
        Get expected bars for a specific session on a trading date.

        Args:
            trading_date: Trading date in YYYYMMDD format
            session_phase: Session phase (granular: 'night', 'morning', 'afternoon'
                          or aggregated: 'night_session', 'day_session')

        Returns:
            Expected bar count for the session (computed from bar_size_minutes):
            - 0 for night/night_session if has_night=False
            - Session-specific bars otherwise (derived from PHASE_TRADING_MINUTES)
        """
        # Check if this is a night session (either granular or aggregated)
        is_night_phase = session_phase in ('night', 'night_session')

        if is_night_phase:
            if self.has_night_session(trading_date):
                return self._expected_bars.get(session_phase, self._expected_night_bars)
            return 0

        # For non-night phases, return expected bars from config
        return self._expected_bars.get(session_phase, 0)

    @property
    def expected_night_bars(self) -> int:
        """Expected bars in night session (computed from bar_size_minutes)."""
        return self._expected_night_bars

    @property
    def expected_morning_bars(self) -> int:
        """Expected bars in morning session (computed from bar_size_minutes)."""
        return self._expected_morning_bars

    @property
    def expected_afternoon_bars(self) -> int:
        """Expected bars in afternoon session (computed from bar_size_minutes)."""
        return self._expected_afternoon_bars

    @property
    def expected_day_session_bars(self) -> int:
        """Expected bars in day session (aggregated, computed from bar_size_minutes)."""
        return self._expected_day_session_bars

    @property
    def expected_night_session_bars(self) -> int:
        """Expected bars in night session (aggregated, computed from bar_size_minutes)."""
        return self._expected_night_session_bars

    @property
    def expected_full_day_bars(self) -> int:
        """Expected total bars for a full day with night session (computed from bar_size_minutes)."""
        return self._expected_full_day_bars

    @property
    def expected_day_only_bars(self) -> int:
        """Expected total bars for a day without night session (computed from bar_size_minutes)."""
        return self._expected_day_only_bars

    def get_expected_phase_bars(self, phase: str) -> int:
        """
        Get expected bars for any phase (generic accessor).

        Args:
            phase: Phase name (granular or aggregated)

        Returns:
            Expected bar count for the phase
        """
        return self._expected_bars.get(phase, 0)


# Module-level singleton for convenience
_loaders: Dict[str, SessionAvailabilityLoader] = {}


def get_session_availability_loader(
    market: str,
    instrument: str,
    bar_size_minutes: int,
    bar_size: Optional[str] = None
) -> SessionAvailabilityLoader:
    """
    Get or create a SessionAvailabilityLoader instance.

    Uses singleton pattern to avoid reloading data.

    Args:
        market: Market code (e.g., 'SHFE')
        instrument: Instrument name (e.g., 'aluminum')
        bar_size_minutes: Bar size in minutes for expected bar calculations (required)
        bar_size: Optional bar size string ('5m', '15m', '30m', '1h').
                  For 30m/1h, uses aggregated phases.

    Returns:
        SessionAvailabilityLoader instance
    """
    bar_size_key = bar_size or "granular"
    key = f"{market.upper()}_{instrument}_{bar_size_minutes}m_{bar_size_key}"

    if key not in _loaders:
        _loaders[key] = SessionAvailabilityLoader(
            market, instrument, bar_size_minutes, bar_size=bar_size
        )

    return _loaders[key]