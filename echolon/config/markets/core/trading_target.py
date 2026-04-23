"""
Trading Target - minimal market/instrument/frequency/capital bundle.

Historically this module also defined ``TradingTargetConfigSchema`` (hard
constraints, objectives, session constraints) that host apps populated into
``TradingTarget.target``. Those performance targets are host-app workflow
state — echolon is a library and should not carry them — so the whole schema
was removed at E1. Host apps now own their own target schemas (e.g. qorka's
``QorkaTarget``) and inject parameters into echolon APIs explicitly.

Remaining here: the thin ``TradingTarget`` model for initial_capital +
market/instrument identification. This stays until E2 promotes
initial_capital onto ``TradingContext`` directly and ``TradingTarget`` is
deleted as well.
"""

from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


# =============================================================================
# Type Definitions
# =============================================================================

# Supported frequency values
FrequencyType = Literal["interday", "intraday"]

# Supported bar sizes
BarSizeType = Literal["1m", "5m", "15m", "30m", "1h", "1d"]

# Frequency-to-bar-size compatibility
VALID_BAR_SIZES = {
    "interday": ["1d"],
    "intraday": ["1m", "5m", "15m", "30m", "1h"],
}


# =============================================================================
# Trading Target Model
# =============================================================================

class TradingTarget(BaseModel):
    """
    Thin market/instrument/frequency/capital bundle.

    Host apps used to construct this from state.json via MarketFactory;
    post-E1 they build it directly from their own session loaders and
    pass it to :meth:`MarketFactory.create`. E2 will promote
    ``initial_capital`` onto :class:`TradingContext` and delete this class.

    Field naming convention:
    - instrument: Full name (e.g., "aluminum", "copper")
    - instrument_code: Short code (e.g., "al", "cu")
    """

    # Market identification
    market: str = Field(
        description="Market code (e.g., 'SHFE', 'CRYPTO')"
    )

    # Instrument identification
    instrument: str = Field(
        description="Instrument full name (e.g., 'aluminum', 'copper')"
    )
    instrument_code: str = Field(
        description="Instrument short code (e.g., 'al', 'cu')"
    )

    # Trading frequency configuration
    frequency: FrequencyType = Field(
        description="Trading frequency: 'interday' (daily) or 'intraday' (sub-daily)"
    )
    bar_size: BarSizeType = Field(
        default="1d",
        description="Bar size: '1m', '5m', '15m', '30m', '1h', '1d'"
    )

    # Capital configuration
    initial_capital: float = Field(
        default=200000.0,
        gt=0,
        description="Initial capital for backtesting and live trading"
    )

    # ==========================================================================
    # Validators
    # ==========================================================================

    @field_validator('market')
    @classmethod
    def validate_market(cls, v: str) -> str:
        """Normalize market code to uppercase."""
        return v.upper()

    @field_validator('instrument', 'instrument_code')
    @classmethod
    def validate_instrument(cls, v: str) -> str:
        """Normalize instrument to lowercase."""
        return v.lower()

    @field_validator('frequency', mode='before')
    @classmethod
    def validate_frequency(cls, v: str) -> str:
        """Normalize and validate frequency."""
        if v is None:
            return 'interday'
        v_lower = v.lower()
        # Handle aliases
        if v_lower in ('daily', 'day', '1d'):
            return 'interday'
        if v_lower in ('minute', 'min', 'intra'):
            return 'intraday'
        if v_lower not in ('interday', 'intraday'):
            raise ValueError(
                f"Invalid frequency: '{v}'. Must be 'interday' or 'intraday'"
            )
        return v_lower

    @field_validator('bar_size', mode='before')
    @classmethod
    def validate_bar_size(cls, v: str) -> str:
        """Normalize bar size format."""
        if v is None:
            return '1d'
        v_lower = v.lower().strip()
        # Handle aliases
        aliases = {
            '1min': '1m', '1minute': '1m',
            '5min': '5m', '5minute': '5m',
            '15min': '15m', '15minute': '15m',
            '30min': '30m', '30minute': '30m',
            '1hour': '1h', '60m': '1h', '60min': '1h',
            '1day': '1d', 'daily': '1d', 'day': '1d',
        }
        return aliases.get(v_lower, v_lower)

    @model_validator(mode='after')
    def validate_frequency_bar_size_compatibility(self) -> 'TradingTarget':
        """Ensure bar_size is compatible with frequency."""
        valid_sizes = VALID_BAR_SIZES.get(self.frequency, [])
        if self.bar_size not in valid_sizes:
            raise ValueError(
                f"Bar size '{self.bar_size}' is not valid for frequency '{self.frequency}'. "
                f"Valid options: {valid_sizes}"
            )
        return self

    # ==========================================================================
    # Convenience Properties
    # ==========================================================================

    @property
    def is_intraday(self) -> bool:
        """Check if trading intraday."""
        return self.frequency == "intraday"

    @property
    def is_interday(self) -> bool:
        """Check if trading interday (daily)."""
        return self.frequency == "interday"

    @property
    def bar_minutes(self) -> int:
        """Get bar size in minutes."""
        return {
            '1m': 1, '5m': 5, '15m': 15, '30m': 30, '1h': 60, '1d': 1440
        }.get(self.bar_size, 1440)

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return self.model_dump()
