"""Trade log schema - contract for backtest_trades.csv.

Producer: modules/quant_engine/backtest/engine/backtrader_engine.py
Consumer: modules/backtest_metrics/utils/backtest_loader.py

Version: 1.1
Created: 2026-01-15
Updated: 2026-01-31 - Made frequency-adaptive (interday vs intraday)

This schema defines the 30-column structure for backtest_trades.csv.
It handles both interday (with entry_regime) and intraday (with session fields).
"""

import math
from pydantic import BaseModel, Field, ConfigDict, field_validator
from typing import Optional, Literal, List
from datetime import datetime, date


def _is_nan(v) -> bool:
    """Check if value is NaN (handles float NaN from pandas)."""
    if v is None:
        return True
    if isinstance(v, float) and math.isnan(v):
        return True
    if v == '':
        return True
    return False


class TradeRecordSchema(BaseModel):
    """
    Schema for a single trade record in backtest_trades.csv (30 columns).

    Frequency-Adaptive Validation:
    - INTERDAY: entry_time/exit_time are date-only, session fields are None
    - INTRADAY: entry_time/exit_time are full datetime, session fields required

    REQUIRED FIELDS (always present):
    - Entry/exit dates, prices
    - Direction, size
    - PnL fields (pnl, commission, pnlcomm, return_pct)
    - Exit reason

    CONDITIONAL FIELDS (frequency-dependent):
    - entry_regime: Present in INTERDAY strategies
    - entry_session_phase, entry_session_type, session_id, etc.: Present in INTRADAY

    OPTIONAL FIELDS (may be missing):
    - MFE/MAE metrics (mfe_points, mae_points, etc.)
    - Entry quality metrics (entry_drawdown_points, entry_quality_score)
    - Profit capture metrics (profit_capture_rate, profit_left_on_table)
    """
    model_config = ConfigDict(extra='allow')  # Forward compatibility

    # ========================================
    # REQUIRED FIELDS - Entry/Exit Basic Info
    # ========================================
    entry_date: date = Field(description="Entry date (YYYY-MM-DD)")
    exit_date: date = Field(description="Exit date (YYYY-MM-DD)")

    # Optional for interday (date-only), required for intraday (full datetime)
    entry_time: Optional[datetime] = Field(
        None,
        description="Entry datetime. INTERDAY: date at midnight. INTRADAY: full datetime."
    )
    exit_time: Optional[datetime] = Field(
        None,
        description="Exit datetime. INTERDAY: date at midnight or None. INTRADAY: full datetime."
    )

    direction: Literal['long', 'short'] = Field(description="Trade direction")
    size: float = Field(gt=0, description="Position size (contracts/shares)")

    entry_price: float = Field(gt=0, description="Entry price")
    exit_price: float = Field(gt=0, description="Exit price")

    # ========================================
    # REQUIRED FIELDS - PnL Metrics
    # ========================================
    pnl: float = Field(description="Profit/Loss before commission")
    commission: float = Field(ge=0, description="Total commission paid")
    pnlcomm: float = Field(description="Net PnL after commission")
    return_pct: float = Field(description="Return percentage")

    exit_reason: Optional[str] = Field(
        None,
        description="Why trade was exited (strategy_exit, stop_loss, etc.)"
    )

    # ========================================
    # CONDITIONAL FIELDS - Frequency Dependent
    # ========================================

    # INTERDAY ONLY
    entry_regime: Optional[str] = Field(
        None,
        description="Market regime at entry execution date (ranging, trending_up, trending_down, volatile). INTERDAY only."
    )
    decision_regime: Optional[str] = Field(
        None,
        description="Market regime at signal generation date — previous trading day before entry. INTERDAY only."
    )

    # INTRADAY ONLY - All optional to support interday
    entry_session_phase: Optional[str] = Field(
        None,
        description="Session phase at entry (night, morning, afternoon). INTRADAY only."
    )
    entry_session_type: Optional[str] = Field(
        None,
        description="Session type (day, night). INTRADAY only."
    )
    session_id: Optional[str] = Field(
        None,
        description="Session identifier (YYYY-MM-DD_day). INTRADAY only."
    )
    entry_bar_of_session: Optional[int] = Field(
        None,
        ge=0,
        description="Bar number at entry within session. INTRADAY only."
    )
    exit_bar_of_session: Optional[int] = Field(
        None,
        ge=0,
        description="Bar number at exit within session. INTRADAY only."
    )
    total_bars_in_session: Optional[int] = Field(
        None,
        ge=0,
        description="Total bars in the session. INTRADAY only."
    )

    # ========================================
    # OPTIONAL FIELDS - MFE/MAE Metrics
    # ========================================
    mfe_points: Optional[float] = Field(
        None,
        description="Maximum Favorable Excursion in price points"
    )
    mae_points: Optional[float] = Field(
        None,
        description="Maximum Adverse Excursion in price points (negative value)"
    )
    mfe_pct: Optional[float] = Field(
        None,
        description="MFE as percentage of entry price"
    )
    mae_pct: Optional[float] = Field(
        None,
        description="MAE as percentage of entry price (negative value)"
    )
    mfe_currency: Optional[float] = Field(
        None,
        description="MFE in currency terms"
    )
    mae_currency: Optional[float] = Field(
        None,
        description="MAE in currency terms (negative value)"
    )

    # ========================================
    # OPTIONAL FIELDS - Profit Capture Metrics
    # ========================================
    profit_capture_rate: Optional[float] = Field(
        None,
        description="Percentage of MFE captured as actual profit"
    )
    profit_left_on_table: Optional[float] = Field(
        None,
        description="Unrealized profit from MFE peak to exit"
    )

    # ========================================
    # OPTIONAL FIELDS - Entry Quality Metrics
    # ========================================
    entry_drawdown_points: Optional[float] = Field(
        None,
        description="Drawdown from entry to MAE in points"
    )
    entry_quality_score: Optional[float] = Field(
        None,
        description="Quality score for entry timing"
    )

    # ========================================
    # OPTIONAL FIELDS - Contract Info
    # ========================================
    entry_contract: Optional[str] = Field(
        None,
        description="Contract code at entry (e.g., cu2303)"
    )
    price_correction: Optional[float] = Field(
        None,
        description="Price correction applied"
    )
    pnl_correction: Optional[float] = Field(
        None,
        description="PnL correction applied"
    )

    # ========================================
    # VALIDATORS - Handle NaN and format differences
    # ========================================

    @field_validator('entry_date', 'exit_date', mode='before')
    @classmethod
    def parse_dates(cls, v):
        """Parse date strings to date objects."""
        if isinstance(v, str):
            return datetime.strptime(v, '%Y-%m-%d').date()
        if isinstance(v, date):
            return v
        return v

    @field_validator('entry_time', 'exit_time', mode='before')
    @classmethod
    def parse_datetimes(cls, v):
        """Parse datetime strings to datetime objects.

        Frequency-adaptive:
        - INTERDAY: Date-only string 'YYYY-MM-DD' -> datetime at midnight
        - INTRADAY: Full datetime 'YYYY-MM-DD HH:MM:SS' -> datetime
        - NaN/None/empty -> None
        """
        if _is_nan(v):
            return None

        if isinstance(v, datetime):
            return v

        if isinstance(v, str):
            # Full datetime format (intraday)
            if len(v) > 10:
                return datetime.strptime(v, '%Y-%m-%d %H:%M:%S')
            # Date-only format (interday) -> datetime at midnight
            return datetime.strptime(v, '%Y-%m-%d')
        return v

    @field_validator(
        'entry_session_phase', 'entry_session_type', 'session_id',
        'entry_regime', 'decision_regime', 'exit_reason', 'entry_contract',
        mode='before'
    )
    @classmethod
    def parse_optional_strings(cls, v):
        """Convert NaN to None for optional string fields.

        This handles pandas NaN values from CSV loading.
        """
        if _is_nan(v):
            return None
        return str(v) if v is not None else None

    @field_validator(
        'entry_bar_of_session', 'exit_bar_of_session', 'total_bars_in_session',
        mode='before'
    )
    @classmethod
    def parse_optional_ints(cls, v):
        """Convert NaN to None for optional integer fields."""
        if _is_nan(v):
            return None
        if isinstance(v, float):
            return int(v)
        return v

    @field_validator(
        'mfe_points', 'mae_points', 'mfe_pct', 'mae_pct',
        'mfe_currency', 'mae_currency',
        'profit_capture_rate', 'profit_left_on_table',
        'entry_drawdown_points', 'entry_quality_score',
        'price_correction', 'pnl_correction',
        mode='before'
    )
    @classmethod
    def parse_optional_floats(cls, v):
        """Convert NaN to None for optional float fields."""
        if _is_nan(v):
            return None
        return v


def validate_trade_log_dataframe(
    df_dict_records: List[dict],
    frequency: str = "interday"
) -> List[TradeRecordSchema]:
    """
    Validate entire trade log DataFrame with frequency-adaptive rules.

    Parameters
    ----------
    df_dict_records : list[dict]
        List of trade records as dictionaries (from df.to_dict('records'))
    frequency : str
        Trading frequency: 'interday' or 'intraday'

    Returns
    -------
    list[TradeRecordSchema]
        List of validated trade records

    Raises
    ------
    ValueError
        If any trade fails validation, with detailed error messages
    """
    validated_trades = []
    errors = []
    is_intraday = frequency.lower() == 'intraday'

    for idx, record in enumerate(df_dict_records):
        try:
            validated = TradeRecordSchema(**record)

            # Frequency-specific validation
            if is_intraday:
                # Intraday requires session fields
                missing_session = []
                if validated.entry_session_phase is None:
                    missing_session.append('entry_session_phase')
                if validated.session_id is None:
                    missing_session.append('session_id')
                if missing_session:
                    errors.append(
                        f"Row {idx}: INTRADAY requires session fields: {missing_session}"
                    )
                    continue
            else:
                # Interday: session fields should be None (already handled by schema)
                pass

            validated_trades.append(validated)
        except Exception as e:
            errors.append(f"Row {idx}: {e}")

    if errors:
        error_msg = f"Trade log validation failed for {len(errors)} / {len(df_dict_records)} trades:\n"
        error_msg += "\n".join(errors[:10])  # Show first 10 errors
        if len(errors) > 10:
            error_msg += f"\n... and {len(errors) - 10} more errors"
        raise ValueError(error_msg)

    return validated_trades


def validate_trades_dict_list(
    trades: List[dict],
    frequency: str = "interday"
) -> List[dict]:
    """
    Validate trades and return as list of dicts (for DataFrame construction).

    This is a convenience wrapper that validates then converts back to dict format
    for DataFrame compatibility.

    Parameters
    ----------
    trades : list[dict]
        List of trade records as dictionaries
    frequency : str
        Trading frequency: 'interday' or 'intraday'

    Returns
    -------
    list[dict]
        List of validated trade records as dictionaries
    """
    validated = validate_trade_log_dataframe(trades, frequency=frequency)
    return [trade.model_dump() for trade in validated]
