"""Strategy log schema - contract for Bridge_default.csv.

Producer: modules/quant_engine/backtest/engine/analyzers.py (StrategyLog analyzer)
Consumer: modules/backtest_metrics/utils/backtest_loader.py

Version: 1.0
Created: 2026-01-15

This schema defines the bar-by-bar strategy decision log structure.
Each row represents a single bar's decision process across all strategy components:
- Entry signal evaluation
- Exit signal evaluation
- Position sizing calculation
- Risk management check
- Order submission and execution

File naming: Bridge_default.csv (where 'default' is the strategy instance name)
"""

from datetime import datetime as dt
from typing import Optional, Literal
from math import isnan
from pydantic import BaseModel, Field, ConfigDict, field_validator, model_validator


class StrategyLogRecordSchema(BaseModel):
    """
    Schema for a single bar's strategy decision record.

    Captures the complete decision flow for one bar:
    1. Entry evaluation → 2. Exit evaluation → 3. Sizing → 4. Risk check → 5. Order → 6. Execution
    """
    model_config = ConfigDict(extra='allow')

    # ========================================
    # BAR METADATA
    # ========================================
    datetime: dt = Field(
        description="Bar datetime (YYYY-MM-DD HH:MM:SS format)"
    )
    bar_count: int = Field(
        ge=1,
        description="Sequential bar number from start of backtest"
    )

    # ========================================
    # ENTRY SIGNAL COMPONENT
    # ========================================
    entry_signal: Literal['HOLD', 'LONG', 'SHORT'] = Field(
        description="Entry signal output: HOLD (no entry), LONG, or SHORT"
    )
    entry_strength: float = Field(
        ge=0.0,
        le=1.0,
        description="Signal strength/confidence (0.0 to 1.0)"
    )
    entry_type: Optional[str] = Field(
        None,
        description="Entry type: 'hold', 'entry_long', 'entry_short', or None"
    )
    entry_reason: str = Field(
        description="Human-readable explanation of entry decision"
    )
    entry_regime: Optional[str] = Field(
        None,
        description="Market regime/session phase at entry evaluation"
    )

    # ========================================
    # EXIT SIGNAL COMPONENT
    # ========================================
    exit_should_exit: bool = Field(
        description="Whether exit signal triggered"
    )
    exit_reason: str = Field(
        description="Exit reason or 'No position to exit'"
    )
    exit_position_size: float = Field(
        ge=0.0,
        description="Current position size for exit evaluation"
    )
    exit_bars_since_entry: int = Field(
        ge=0,
        description="Bars held since entry (0 if no position)"
    )

    # ========================================
    # POSITION SIZING COMPONENT
    # ========================================
    sizing_calculated_size: float = Field(
        ge=0.0,
        description="Final calculated position size"
    )
    sizing_raw_size: float = Field(
        ge=0.0,
        description="Raw size before adjustments"
    )
    sizing_signal_direction: Literal['HOLD', 'LONG', 'SHORT'] = Field(
        description="Direction for sizing calculation"
    )
    sizing_reason: str = Field(
        description="Sizing calculation explanation"
    )

    # ========================================
    # RISK MANAGEMENT COMPONENT
    # ========================================
    risk_trading_allowed: bool = Field(
        description="Whether trading is allowed by risk manager"
    )
    risk_reason: str = Field(
        description="Risk check result explanation"
    )

    # ========================================
    # ORDER MANAGEMENT
    # ========================================
    order_action: Optional[str] = Field(
        None,
        description="Order action: 'submit' or None"
    )
    order_side: Optional[str] = Field(
        None,
        description="Order side (buy/sell indicator)"
    )
    order_size: float = Field(
        ge=0.0,
        description="Order size submitted"
    )
    order_status: Optional[str] = Field(
        None,
        description="Order status"
    )
    order_ref: Optional[str] = Field(
        None,
        description="Order reference ID"
    )
    order_executed: bool = Field(
        description="Whether order was executed"
    )

    # ========================================
    # EXECUTION DETAILS
    # ========================================
    execution_date: Optional[dt] = Field(
        None,
        description="Execution datetime (nullable)"
    )
    execution_price: float = Field(
        ge=0.0,
        description="Execution price"
    )
    execution_size: float = Field(
        ge=0.0,
        description="Executed size"
    )

    # ========================================
    # FORCED EXIT (CONTRACT EXPIRY, SESSION END)
    # ========================================
    is_forced_exit: bool = Field(
        description="Whether this was a forced exit (contract expiry, session end)"
    )
    forced_exit_reason: Optional[str] = Field(
        None,
        description="Forced exit reason (nullable)"
    )

    @model_validator(mode='before')
    @classmethod
    def convert_nan_to_none(cls, values):
        """Convert NaN values to None for proper Optional field handling."""
        if isinstance(values, dict):
            for key, value in values.items():
                if isinstance(value, float):
                    try:
                        if isnan(value):
                            values[key] = None
                    except (TypeError, ValueError):
                        pass
        return values

    @field_validator('datetime', mode='before')
    @classmethod
    def parse_datetime(cls, v):
        """Parse datetime string to datetime object.

        Frequency-adaptive:
        - INTERDAY: Date-only string 'YYYY-MM-DD' -> datetime at midnight
        - INTRADAY: Full datetime 'YYYY-MM-DD HH:MM:SS' -> datetime
        """
        if isinstance(v, dt):
            return v
        if isinstance(v, str):
            # Full datetime format (intraday)
            if len(v) > 10:
                return dt.strptime(v, '%Y-%m-%d %H:%M:%S')
            # Date-only format (interday) -> datetime at midnight
            return dt.strptime(v, '%Y-%m-%d')
        return v

    @field_validator('execution_date', mode='before')
    @classmethod
    def parse_execution_date(cls, v):
        """Parse execution_date, handling empty strings, NaN, and datetime strings.

        Frequency-adaptive:
        - INTERDAY: Date-only string 'YYYY-MM-DD' -> datetime at midnight
        - INTRADAY: Full datetime 'YYYY-MM-DD HH:MM:SS' -> datetime
        """
        if v is None or v == '':
            return None
        if isinstance(v, float) and isnan(v):
            return None
        if isinstance(v, dt):
            return v
        if isinstance(v, str):
            # Full datetime format (intraday)
            if len(v) > 10:
                return dt.strptime(v, '%Y-%m-%d %H:%M:%S')
            # Date-only format (interday) -> datetime at midnight
            return dt.strptime(v, '%Y-%m-%d')
        return v


def validate_strategy_log_dataframe(df_dict_records: list[dict]) -> list[StrategyLogRecordSchema]:
    """
    Validate entire strategy log DataFrame.

    Parameters
    ----------
    df_dict_records : list[dict]
        List of strategy log records as dictionaries (from df.to_dict('records'))

    Returns
    -------
    list[StrategyLogRecordSchema]
        List of validated strategy log records

    Raises
    ------
    ValueError
        If any record fails validation, with detailed error messages
    """
    validated_records = []
    errors = []

    for idx, record in enumerate(df_dict_records):
        try:
            validated = StrategyLogRecordSchema(**record)
            validated_records.append(validated)
        except Exception as e:
            errors.append(f"Row {idx}: {e}")

    if errors:
        error_msg = f"Strategy log validation failed for {len(errors)} / {len(df_dict_records)} records:\n"
        error_msg += "\n".join(errors[:10])
        if len(errors) > 10:
            error_msg += f"\n... and {len(errors) - 10} more errors"
        raise ValueError(error_msg)

    return validated_records


def validate_strategy_log_dict_list(records: list[dict]) -> list[dict]:
    """
    Validate strategy log records and return as list of dicts.

    This is a convenience wrapper that validates then converts back to dict format
    for DataFrame compatibility.

    Parameters
    ----------
    records : list[dict]
        List of strategy log records as dictionaries

    Returns
    -------
    list[dict]
        List of validated strategy log records as dictionaries
    """
    validated = validate_strategy_log_dataframe(records)
    return [record.model_dump() for record in validated]
