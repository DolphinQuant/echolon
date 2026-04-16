"""
Trading Target Schema - Pydantic model for session/state.json.

Defines the validated schema for user's trading target configuration.
This is the single source of truth for state.json structure.

Usage:
    from config.markets.core.trading_target import TradingTarget

    # Load and validate state.json
    target = TradingTarget.load()

    # Access typed fields
    print(target.market)           # "SHFE"
    print(target.instrument)       # "aluminum"
    print(target.instrument_code)  # "al"
    print(target.frequency)        # "intraday"
    print(target.bar_size)         # "5m"

    # Access trading targets (typed)
    if target.target:
        print(target.target.primary_objective)
        print(target.target.hard_constraints)
"""

import json
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


# =============================================================================
# Type Definitions
# =============================================================================

# Supported frequency values
FrequencyType = Literal["interday", "intraday"]

# Supported bar sizes
BarSizeType = Literal["1m", "5m", "15m", "30m", "1h", "1d"]

# Supported operators for target metrics
OperatorType = Literal["<=", ">=", "maximize_within_range", "within_range"]

# Frequency-to-bar-size compatibility
VALID_BAR_SIZES = {
    "interday": ["1d"],
    "intraday": ["1m", "5m", "15m", "30m", "1h"],
}


# =============================================================================
# Target Metric Schemas
# =============================================================================

class TargetMetricSchema(BaseModel):
    """
    Individual performance target metric.

    Supports both single-value targets (target + operator)
    and range targets (target_min + target_max + operator).
    """
    model_config = ConfigDict(extra='allow')

    # Single-value target
    target: Optional[float] = Field(
        default=None,
        description="Target value for single-value constraints"
    )

    # Range target
    target_min: Optional[float] = Field(
        default=None,
        description="Minimum value for range constraints"
    )
    target_max: Optional[float] = Field(
        default=None,
        description="Maximum value for range constraints"
    )

    # Operator
    operator: OperatorType = Field(
        description="Comparison operator: '<=', '>=', 'maximize_within_range', 'within_range'"
    )

    # Description
    description: str = Field(
        description="Human-readable description of this metric"
    )

    @model_validator(mode='after')
    def validate_target_values(self) -> 'TargetMetricSchema':
        """Ensure appropriate target values are set based on operator."""
        if self.operator in ('<=', '>='):
            if self.target is None:
                raise ValueError(
                    f"Operator '{self.operator}' requires 'target' value"
                )
        elif self.operator in ('maximize_within_range', 'within_range'):
            if self.target_min is None or self.target_max is None:
                raise ValueError(
                    f"Operator '{self.operator}' requires 'target_min' and 'target_max'"
                )
        return self


class SessionConstraintsSchema(BaseModel):
    """
    Intraday-specific session constraints.

    Defines rules for position management within trading sessions.
    """
    model_config = ConfigDict(extra='allow')

    flatten_before_close: bool = Field(
        default=True,
        description="Whether to close all positions before session end"
    )
    avoid_opening_bars: int = Field(
        default=0,
        ge=0,
        description="Number of bars to avoid at session open"
    )
    avoid_closing_bars: int = Field(
        default=0,
        ge=0,
        description="Number of bars to avoid at session close"
    )
    description: Optional[str] = Field(
        default=None,
        description="Human-readable description of session constraints"
    )


# =============================================================================
# Explicit Constraint/Objective Schemas
# =============================================================================

class HardConstraintsSchema(BaseModel):
    """
    Hard constraints - non-negotiable performance limits.

    These must be satisfied for a strategy to be considered viable.
    """
    model_config = ConfigDict(extra='allow')

    # Required for all frequencies
    max_drawdown_pct: TargetMetricSchema = Field(
        description="Maximum loss from peak equity. Non-negotiable limit."
    )

    # Intraday only
    max_session_loss_pct: Optional[TargetMetricSchema] = Field(
        default=None,
        description="Maximum loss in a single session. Intraday only."
    )


class PrimaryObjectiveSchema(BaseModel):
    """
    Primary objective - the main optimization goal.

    This is THE metric that defines strategy excellence.
    """
    model_config = ConfigDict(extra='allow')

    # Required for all frequencies
    sharpe_ratio_annual: TargetMetricSchema = Field(
        description="Risk-adjusted returns. Primary optimization target."
    )


class SecondaryObjectiveSchema(BaseModel):
    """
    Secondary objectives - optimized after primary is met.

    These provide additional optimization targets once the primary
    objective is satisfied.
    """
    model_config = ConfigDict(extra='allow')

    # Common to both frequencies
    average_trades_per_week: Optional[TargetMetricSchema] = Field(
        default=None,
        description="Weekly trade frequency target."
    )
    average_annual_return_pct: Optional[TargetMetricSchema] = Field(
        default=None,
        description="Absolute return target."
    )

    # Intraday only
    average_trades_per_session: Optional[TargetMetricSchema] = Field(
        default=None,
        description="Trades per session. Intraday only."
    )


class TradingTargetConfigSchema(BaseModel):
    """
    Performance targets configuration.

    Loaded from trading_target_interday.json or trading_target_intraday.json.
    Contains hard constraints, objectives, and optimization instructions.

    Structure:
    - hard_constraints: Non-negotiable limits (e.g., max drawdown)
    - primary_objective: Main optimization goal (e.g., Sharpe ratio)
    - secondary_objective: Additional goals when primary is met
    - session_constraints: Intraday-specific rules (optional)
    - optimization_instruction: Human-readable optimization guidance
    """
    model_config = ConfigDict(extra='allow')

    description: str = Field(
        description="Description of the trading target configuration"
    )

    # Hard constraints - must be satisfied
    hard_constraints: HardConstraintsSchema = Field(
        description="Non-negotiable performance limits"
    )

    # Primary objective - main optimization goal
    primary_objective: PrimaryObjectiveSchema = Field(
        description="Primary optimization target"
    )

    # Secondary objectives - optimize after primary is met
    secondary_objective: Optional[SecondaryObjectiveSchema] = Field(
        default=None,
        description="Secondary optimization targets"
    )

    # Session constraints - intraday only
    session_constraints: Optional[SessionConstraintsSchema] = Field(
        default=None,
        description="Intraday-specific session management rules"
    )

    # Optimization instruction
    optimization_instruction: str = Field(
        description="Human-readable optimization guidance"
    )

    # Integrated fields from output/target.json (optional)
    integrated_constraints: Optional[str] = Field(
        default=None,
        description="Integrated constraints from target definition"
    )
    integrated_preferences: Optional[str] = Field(
        default=None,
        description="Integrated preferences from target definition"
    )
    integrated_notes: Optional[str] = Field(
        default=None,
        description="Integrated notes from target definition"
    )

    # ==========================================================================
    # Convenience Properties
    # ==========================================================================

    @property
    def max_drawdown_target(self) -> Optional[float]:
        """Get max drawdown constraint value."""
        return self.hard_constraints.max_drawdown_pct.target

    @property
    def max_session_loss_target(self) -> Optional[float]:
        """Get max session loss constraint value (intraday only)."""
        if self.hard_constraints.max_session_loss_pct:
            return self.hard_constraints.max_session_loss_pct.target
        return None

    @property
    def sharpe_target(self) -> Optional[float]:
        """Get Sharpe ratio target value."""
        return self.primary_objective.sharpe_ratio_annual.target

    @property
    def annual_return_target(self) -> Optional[float]:
        """Get annual return target value."""
        if self.secondary_objective and self.secondary_objective.average_annual_return_pct:
            return self.secondary_objective.average_annual_return_pct.target
        return None

    @property
    def is_intraday_config(self) -> bool:
        """Check if this is an intraday configuration."""
        return self.session_constraints is not None


# =============================================================================
# Trading Target Model
# =============================================================================

class TradingTarget(BaseModel):
    """
    User's trading target configuration.

    Loaded from session/state.json, this model captures what the user
    wants to trade and validates all fields before operations begin.

    Field naming convention:
    - instrument: Full name (e.g., "aluminum", "copper")
    - instrument_code: Short code (e.g., "al", "cu")
    """

    # User request (optional, for context)
    user_request: Optional[str] = Field(
        default=None,
        description="User's natural language request"
    )

    # Market identification
    market: str = Field(
        description="Market code (e.g., 'SHFE', 'CRYPTO')"
    )
    market_full_name: Optional[str] = Field(
        default=None,
        description="Full market name (e.g., 'Shanghai Futures Exchange')"
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

    # Target configuration from trading_target_interday.json or trading_target_intraday.json
    # Contains: hard_constraints, primary_objective, secondary_objective, session_constraints (intraday)
    target: Optional[TradingTargetConfigSchema] = Field(
        default=None,
        description="Trading target configuration (hard_constraints, objectives, etc.)"
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

    # ==========================================================================
    # I/O Methods
    # ==========================================================================

    @classmethod
    def load(cls, path: Optional[str] = None) -> 'TradingTarget':
        """
        Load and validate trading target from JSON file.

        Args:
            path: Path to state.json. Defaults to session/state.json

        Returns:
            Validated TradingTarget instance

        Raises:
            FileNotFoundError: If state file doesn't exist
            ValidationError: If state file has invalid content
        """
        if path is None:
            path = Path(__file__).parent.parent.parent.parent / "session" / "state.json"
        else:
            path = Path(path)

        with open(path, 'r') as f:
            data = json.load(f)

        return cls.model_validate(data)

    def save(self, path: Optional[str] = None) -> None:
        """
        Save trading target to JSON file.

        Args:
            path: Path to save. Defaults to session/state.json
        """
        if path is None:
            path = Path(__file__).parent.parent.parent.parent / "session" / "state.json"
        else:
            path = Path(path)

        path.parent.mkdir(parents=True, exist_ok=True)

        with open(path, 'w') as f:
            json.dump(self.model_dump(), f, indent=2)
            f.write('\n')

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return self.model_dump()
