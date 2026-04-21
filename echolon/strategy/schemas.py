"""
Component Output Type Definitions

This module defines the required output formats for each strategy component
to ensure compatibility with the strategy logger interface.

Components must instantiate these Pydantic BaseModel classes which provide:
- Automatic validation at creation time (catches errors immediately)
- Type coercion and constraint enforcement
- Self-documenting field requirements
- Prevention of typos and missing fields

DESIGN PRINCIPLE:
- BaseModel definitions contain ONLY universal coordination fields (stable across strategies)
- Strategy-specific diagnostic fields (indicators, regimes, etc.) are allowed via extra='allow'
- This enables strategy evolution without modifying BaseModel definitions
"""

from typing import Dict, List, Union, Literal, Optional
from pydantic import BaseModel, Field, field_validator, model_validator
import json
import os
import math

# Import OrderIntent for strategy coordination
from echolon.strategy.interfaces import OrderIntent
from echolon.errors import raise_error


# Valid signal enum values shared by EntrySignalOutput and ExitSignalOutput.
# Kept module-level so both schemas reference the same set (VAL-002).
VALID_SIGNALS = {"LONG", "SHORT", "HOLD"}


class EntrySignalOutput(BaseModel):
    """
    Required output format for entry_rule component.

    UNIVERSAL FIELDS (Required):
    - signal: Must be 'LONG', 'SHORT', or 'HOLD'
    - strength: Must be between 0.0 and 1.0 (inclusive)
    - type: Non-empty string (e.g., 'entry_long', 'entry_short', 'hold')
    - entry_reason: Non-empty human-readable reason for the signal
    - intent: OrderIntent for strategy coordination (ENTRY_LONG, ENTRY_SHORT, or None for HOLD)
    - regime: Trading context at time of signal - market regime for interday (trending_up, ranging), session phase for intraday (night, morning, afternoon)

    STRATEGY-SPECIFIC FIELDS (Optional via extra='allow'):
    Components can add diagnostic fields like indicator values, etc.

    Example:
        >>> output = EntrySignalOutput(
        ...     signal='LONG',
        ...     strength=0.85,
        ...     type='entry_long',
        ...     entry_reason='TEMA crossover + trending regime',
        ...     intent=OrderIntent.ENTRY_LONG,
        ...     regime='trending_up',
        ...     # Strategy-specific extras (allowed!)
        ...     tema_short=4580.2
        ... )
    """
    signal: Literal['LONG', 'SHORT', 'HOLD'] = Field(
        ...,
        description="Entry signal direction"
    )
    strength: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Signal strength (0.0-1.0)"
    )
    type: str = Field(
        ...,
        min_length=1,
        description="Signal type (e.g., 'entry_long', 'entry_short', 'hold')"
    )
    entry_reason: str = Field(
        ...,
        min_length=1,
        description="Human-readable reason for the signal"
    )
    intent: Optional[OrderIntent] = Field(
        default=None,
        description="Order intent for strategy execution (ENTRY_LONG, ENTRY_SHORT, or None for HOLD)"
    )
    regime: str = Field(
        ...,
        description="Trading context at time of signal - market regime for interday (trending_up, ranging), session phase for intraday (night, morning, afternoon)"
    )

    @field_validator("signal", mode="before")
    @classmethod
    def _validate_signal_enum(cls, v):
        """Raise VAL-002 on unknown signal values before Pydantic's Literal check.

        Running ``mode='before'`` means this hook fires first; Pydantic's own
        Literal-validator never sees invalid values, so the LLM author gets a
        catalog-coded error instead of a generic ``pydantic.ValidationError``.
        """
        if v not in VALID_SIGNALS:
            raise_error(
                "VAL-002",
                file="EntrySignalOutput",
                method="<signal field>",
                got=repr(v),
            )
        return v

    class Config:
        extra = 'allow'  # Allow strategy-specific diagnostic fields
        arbitrary_types_allowed = True  # Allow Enum types


class ExitSignalOutput(BaseModel):
    """
    Required output format for exit_rule component.

    UNIVERSAL FIELDS (Required):
    - should_exit: Boolean indicating if exit should occur
    - exit_reason: Non-empty human-readable reason for exit decision
    - position_size: Must be >= 0
    - bars_since_entry: Must be >= 0
    - intent: OrderIntent for strategy coordination (EXIT_LONG, EXIT_SHORT, or None if no exit)

    STRATEGY-SPECIFIC FIELDS (Optional via extra='allow'):
    Components can add diagnostic fields like stop_price, atr_distance, etc.

    Example:
        >>> output = ExitSignalOutput(
        ...     should_exit=True,
        ...     exit_reason='Trailing stop hit at 3900.5',
        ...     position_size=10.0,
        ...     bars_since_entry=15,
        ...     intent=OrderIntent.EXIT_LONG,
        ...     # Strategy-specific extras (allowed!)
        ...     stop_price=3900.5,
        ...     atr_distance=2.5
        ... )
    """
    should_exit: bool = Field(
        ...,
        description="Whether to exit position"
    )
    exit_reason: str = Field(
        ...,
        min_length=1,
        description="Human-readable reason for exit decision"
    )
    position_size: float = Field(
        ...,
        ge=0.0,
        description="Current position size (must be non-negative)"
    )
    bars_since_entry: int = Field(
        ...,
        ge=0,
        description="Number of bars since entry (must be non-negative)"
    )
    intent: Optional[OrderIntent] = Field(
        default=None,
        description="Order intent for strategy execution (EXIT_LONG, EXIT_SHORT, or None if no exit)"
    )
    signal: Optional[Literal['LONG', 'SHORT', 'HOLD']] = Field(
        default=None,
        description=(
            "Optional signal direction that produced this exit decision. "
            "Must be 'LONG', 'SHORT', or 'HOLD' when provided."
        )
    )

    @field_validator("signal", mode="before")
    @classmethod
    def _validate_signal_enum(cls, v):
        """Raise VAL-002 on unknown signal values before Pydantic's Literal check.

        Mirror of the ``EntrySignalOutput`` validator so both schemas produce a
        catalog-coded error when an LLM author returns lowercase ``'long'``.
        """
        if v is None:
            return v
        if v not in VALID_SIGNALS:
            raise_error(
                "VAL-002",
                file="ExitSignalOutput",
                method="<signal field>",
                got=repr(v),
            )
        return v

    class Config:
        extra = 'allow'  # Allow strategy-specific diagnostic fields
        arbitrary_types_allowed = True  # Allow Enum types


class SizerOutput(BaseModel):
    """
    Required output format for position_sizer component.

    UNIVERSAL FIELDS (Required):
    - calculated_size: Must be non-negative integer (whole contracts)
    - signal_direction: Must be 'LONG', 'SHORT', or 'HOLD'
    - sizing_reason: Non-empty human-readable reason for sizing decision
    - raw_size: Raw calculated size before floor/validation (float, for analysis)

    STRATEGY-SPECIFIC FIELDS (Optional via extra='allow'):
    Components can add diagnostic fields like volatility_factor, equity_curve_factor, etc.

    Example:
        >>> output = SizerOutput(
        ...     calculated_size=10,
        ...     signal_direction='LONG',
        ...     sizing_reason='Size: 10 contracts (raw: 10.8)',
        ...     raw_size=10.8,
        ...     # Strategy-specific extras (allowed!)
        ...     volatility_factor=0.85,
        ...     equity_curve_factor=1.2
        ... )
    """
    calculated_size: int = Field(
        ...,
        ge=0,
        description="Calculated position size in whole contracts (must be non-negative integer)"
    )
    signal_direction: Literal['LONG', 'SHORT', 'HOLD'] = Field(
        ...,
        description="Direction of position"
    )
    sizing_reason: str = Field(
        ...,
        min_length=1,
        description="Human-readable reason for sizing decision"
    )
    raw_size: float = Field(
        ...,
        ge=0.0,
        description="Raw calculated position size before floor/validation (for analysis and debugging)"
    )

    class Config:
        extra = 'allow'  # Allow strategy-specific diagnostic fields


class RiskOutput(BaseModel):
    """
    Required output format for risk_manager component.

    UNIVERSAL FIELDS (Required):
    - trading_allowed: Boolean indicating if trading is allowed
    - risk_reason: Non-empty human-readable reason for risk decision

    STRATEGY-SPECIFIC FIELDS (Optional via extra='allow'):
    Components can add diagnostic fields like drawdown_pct, consecutive_losses, etc.

    Example:
        >>> output = RiskOutput(
        ...     trading_allowed=False,
        ...     risk_reason='Daily loss limit exceeded (-5.2%)',
        ...     # Strategy-specific extras (allowed!)
        ...     drawdown_pct=-5.2,
        ...     consecutive_losses=3
        ... )
    """
    trading_allowed: bool = Field(
        ...,
        description="Whether trading is allowed"
    )
    risk_reason: str = Field(
        ...,
        min_length=1,
        description="Human-readable reason for risk decision"
    )

    class Config:
        extra = 'allow'  # Allow strategy-specific diagnostic fields


# ============================================================================
# Position Size Type Validation
# ============================================================================

def validate_position_size(size: Union[int, float], component_name: str = "position_sizer") -> int:
    """
    Validate and convert position size to non-negative integer.

    Position sizing components MUST return non-negative integers representing
    the number of contracts to trade. This function enforces that contract.

    Parameters
    ----------
    size : Union[int, float]
        Position size value to validate (can be int or float)
    component_name : str
        Name of component for error messages (default: "position_sizer")

    Returns
    -------
    int
        Validated non-negative integer position size

    Raises
    ------
    TypeError
        If size is not numeric (int or float)
    ValueError
        If size is negative, NaN, or infinite

    Examples
    --------
    >>> validate_position_size(10)
    10
    >>> validate_position_size(10.7)  # Floors to integer
    10
    >>> validate_position_size(0)
    0
    >>> validate_position_size(-5)  # Raises ValueError
    ValueError: position_sizer returned negative size: -5
    >>> validate_position_size(float('nan'))  # Raises ValueError
    ValueError: position_sizer returned invalid size (NaN)
    """
    # Type validation
    if not isinstance(size, (int, float)):
        raise TypeError(
            f"{component_name} must return numeric type (int or float), "
            f"got {type(size).__name__}: {size}"
        )

    # Check for NaN
    if math.isnan(size):
        raise ValueError(f"{component_name} returned invalid size (NaN)")

    # Check for infinity
    if math.isinf(size):
        raise ValueError(f"{component_name} returned invalid size (infinite): {size}")

    # Check for negative
    if size < 0:
        raise ValueError(f"{component_name} returned negative size: {size}")

    # Convert to integer (floor)
    validated_size = int(math.floor(size))

    # Final sanity check
    if validated_size < 0:
        raise ValueError(
            f"{component_name} size became negative after conversion: {size} -> {validated_size}"
        )

    return validated_size


class StrategyIndicatorList(BaseModel):
    """
    Pydantic model for validating strategy_indicator_list.json format.

    This model enforces the EXACT structure required by the backtest system:
    1. indicators_with_lookback: Dict[str, List[int]] - indicator name to [min_period, max_period]
    2. indicators_without_lookback: List[str] - simple list of indicator names
    3. indicators_with_special_params: List[str] - simple list of indicator names

    The data preparation system will generate indicators for ALL periods from min to max (inclusive).
    For example: "ADX": [10, 20] will generate adx_10, adx_11, adx_12, ..., adx_20

    Example valid format:
    {
        "indicators_with_lookback": {
            "ADX": [10, 20],
            "ATR": [10, 20],
            "EMA": [150, 250]
        },
        "indicators_without_lookback": [],
        "indicators_with_special_params": [
            "MACD_LINE",
            "MACD_SIGNAL",
            "BBANDS_UPPER"
        ]
    }
    """

    indicators_with_lookback: Dict[str, List[int]] = Field(
        default_factory=dict,
        description="Indicators with period parameters. Format: {INDICATOR_NAME: [min_period, max_period]}"
    )

    indicators_without_lookback: List[str] = Field(
        default_factory=list,
        description="Indicators without period parameters. Format: [INDICATOR_NAME1, INDICATOR_NAME2, ...]"
    )

    indicators_with_special_params: List[str] = Field(
        default_factory=list,
        description="Indicators with special parameters (e.g., MACD, BBANDS). Format: [INDICATOR_NAME1, INDICATOR_NAME2, ...]"
    )

    system_provided_indicators: Optional[Dict[str, str]] = Field(
        default=None,
        description="Intraday only: Documents auto-generated bar count indicators (bar_of_day, bars_remaining, etc.). This is informational - these indicators are always provided by the system."
    )

    @field_validator('indicators_with_lookback')
    @classmethod
    def validate_lookback_format(cls, v: Dict[str, List[int]]) -> Dict[str, List[int]]:
        """
        Validate that lookback indicators have exactly [min, max] format.

        Rules:
        - Each indicator must have exactly 2 integer values
        - Values must be: [min_period, max_period]
        - min_period <= max_period
        - Both values must be positive integers
        - This will generate indicators for ALL periods from min to max (inclusive)
        """
        for indicator_name, periods in v.items():
            # Check type
            if not isinstance(periods, list):
                raise ValueError(
                    f"Indicator '{indicator_name}' lookback must be a list, got {type(periods).__name__}. "
                    f"Expected format: [min_period, max_period]"
                )

            # Check length - MUST be exactly 2 values
            if len(periods) != 2:
                raise ValueError(
                    f"Indicator '{indicator_name}' must have exactly 2 values [min, max], "
                    f"got {len(periods)} values: {periods}. "
                    f"The system will generate ALL periods from min to max automatically."
                )

            # Check all values are integers
            if not all(isinstance(p, int) for p in periods):
                raise ValueError(
                    f"Indicator '{indicator_name}' periods must be integers, "
                    f"got {periods} with types {[type(p).__name__ for p in periods]}"
                )

            # Check all values are positive
            if not all(p > 0 for p in periods):
                raise ValueError(
                    f"Indicator '{indicator_name}' periods must be positive, got {periods}"
                )

            # Check min <= max
            min_period, max_period = periods
            if min_period > max_period:
                raise ValueError(
                    f"Indicator '{indicator_name}' periods must satisfy min <= max, "
                    f"got min={min_period}, max={max_period}"
                )

        return v

    @field_validator('indicators_without_lookback')
    @classmethod
    def validate_no_lookback_format(cls, v: List[str]) -> List[str]:
        """
        Validate that indicators_without_lookback is a simple list of strings.

        Rules:
        - Must be a list
        - All elements must be non-empty strings
        - No duplicates allowed
        """
        if not isinstance(v, list):
            raise ValueError(
                f"indicators_without_lookback must be a list, got {type(v).__name__}"
            )

        # Check all elements are strings
        for i, indicator in enumerate(v):
            if not isinstance(indicator, str):
                raise ValueError(
                    f"indicators_without_lookback[{i}] must be a string, "
                    f"got {type(indicator).__name__}: {indicator}"
                )

            if not indicator.strip():
                raise ValueError(
                    f"indicators_without_lookback[{i}] cannot be empty or whitespace"
                )

        # Check for duplicates
        if len(v) != len(set(v)):
            duplicates = [item for item in set(v) if v.count(item) > 1]
            raise ValueError(
                f"indicators_without_lookback contains duplicates: {duplicates}"
            )

        return v

    @field_validator('indicators_with_special_params')
    @classmethod
    def validate_special_params_format(cls, v: List[str]) -> List[str]:
        """
        Validate that indicators_with_special_params is a simple list of strings.

        Rules:
        - Must be a list
        - All elements must be non-empty strings
        - No duplicates allowed
        """
        if not isinstance(v, list):
            raise ValueError(
                f"indicators_with_special_params must be a list, got {type(v).__name__}"
            )

        # Check all elements are strings
        for i, indicator in enumerate(v):
            if not isinstance(indicator, str):
                raise ValueError(
                    f"indicators_with_special_params[{i}] must be a string, "
                    f"got {type(indicator).__name__}: {indicator}"
                )

            if not indicator.strip():
                raise ValueError(
                    f"indicators_with_special_params[{i}] cannot be empty or whitespace"
                )

        # Check for duplicates
        if len(v) != len(set(v)):
            duplicates = [item for item in set(v) if v.count(item) > 1]
            raise ValueError(
                f"indicators_with_special_params contains duplicates: {duplicates}"
            )

        return v

    @model_validator(mode='after')
    def validate_no_overlaps(self) -> 'StrategyIndicatorList':
        """
        Ensure no indicator appears in multiple categories.
        """
        lookback_set = set(self.indicators_with_lookback.keys())
        no_lookback_set = set(self.indicators_without_lookback)
        special_params_set = set(self.indicators_with_special_params)

        # Check for overlaps between lookback and no_lookback
        overlap_lookback_no_lookback = lookback_set & no_lookback_set
        if overlap_lookback_no_lookback:
            raise ValueError(
                f"Indicators cannot be in both 'with_lookback' and 'without_lookback': "
                f"{overlap_lookback_no_lookback}"
            )

        # Check for overlaps between lookback and special_params
        overlap_lookback_special = lookback_set & special_params_set
        if overlap_lookback_special:
            raise ValueError(
                f"Indicators cannot be in both 'with_lookback' and 'with_special_params': "
                f"{overlap_lookback_special}"
            )

        # Check for overlaps between no_lookback and special_params
        overlap_no_lookback_special = no_lookback_set & special_params_set
        if overlap_no_lookback_special:
            raise ValueError(
                f"Indicators cannot be in both 'without_lookback' and 'with_special_params': "
                f"{overlap_no_lookback_special}"
            )

        return self

    @model_validator(mode='after')
    def validate_not_empty(self) -> 'StrategyIndicatorList':
        """
        Ensure at least one indicator is defined.
        """
        total_indicators = (
            len(self.indicators_with_lookback) +
            len(self.indicators_without_lookback) +
            len(self.indicators_with_special_params)
        )

        if total_indicators == 0:
            raise ValueError(
                "Strategy must define at least one indicator. "
                "All three categories (with_lookback, without_lookback, with_special_params) are empty."
            )

        return self

    class Config:
        """Pydantic configuration."""
        extra = 'forbid'  # Forbid extra fields not defined in the model
        json_schema_extra = {
            "example": {
                "indicators_with_lookback": {
                    "ADX": [10, 20],
                    "ATR": [10, 20],
                    "EMA": [150, 250],
                    "RSI": [10, 20],
                    "SMA": [30, 70]
                },
                "indicators_without_lookback": [],
                "indicators_with_special_params": [
                    "MACD_LINE",
                    "MACD_SIGNAL",
                    "MACD_HISTOGRAM",
                    "MAMA",
                    "FAMA",
                    "BBANDS_UPPER",
                    "BBANDS_MIDDLE",
                    "BBANDS_LOWER"
                ]
            }
        }


def validate_indicator_list_json(file_path: str) -> tuple[bool, str, StrategyIndicatorList]:
    """
    Validate strategy_indicator_list.json file format using Pydantic.

    Args:
        file_path: Path to strategy_indicator_list.json file

    Returns:
        Tuple of (is_valid, error_message, parsed_model)
        - is_valid: True if valid, False otherwise
        - error_message: Empty string if valid, detailed error message if invalid
        - parsed_model: StrategyIndicatorList instance if valid, None if invalid

    Example:
        >>> is_valid, error, model = validate_indicator_list_json("strategy_indicator_list.json")
        >>> if not is_valid:
        >>>     print(f"Validation failed: {error}")
        >>> else:
        >>>     print(f"Valid! Found {len(model.indicators_with_lookback)} lookback indicators")
    """
    # Check file exists
    if not os.path.exists(file_path):
        return False, f"File not found: {file_path}", None

    # Load JSON
    with open(file_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    # Validate with Pydantic
    validated_model = StrategyIndicatorList(**data)
    return True, "", validated_model


__all__ = [
    'EntrySignalOutput',
    'ExitSignalOutput',
    'SizerOutput',
    'RiskOutput',
    'validate_position_size',
    'StrategyIndicatorList',
    'validate_indicator_list_json',
]
