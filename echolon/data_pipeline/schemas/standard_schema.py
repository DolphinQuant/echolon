"""
Standard Market Data Schema
===========================

Defines the canonical schema for data flowing between data_pipeline and indicators modules.
This is the CONTRACT between modules - any change here requires coordination.

Supports:
- Multiple markets: SHFE, crypto (Binance), CME, etc.
- Multiple frequencies: daily (interday), minute (intraday)
- Multiple asset types: futures, perpetuals, spot

Data Flow:
    data_pipeline (extractors/transformers)
        → StandardSchema (this file)
        → indicators (calculators/engine)
        → quant_engine (backtest/deploy)

Schema Tiers:
    TIER 1 - CORE: Always required for any market/frequency
    TIER 2 - FREQUENCY: Required based on data frequency
    TIER 3 - MARKET: Required based on market type
    TIER 4 - OPTIONAL: Nice to have, may be missing
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Dict, Set, Optional, Any
import pandas as pd
import numpy as np
import logging

logger = logging.getLogger(__name__)


# =============================================================================
# Enums for Market and Frequency Types
# =============================================================================

class MarketType(Enum):
    """Supported market types."""
    SHFE = "shfe"           # Shanghai Futures Exchange
    CRYPTO = "crypto"       # Cryptocurrency (Binance, etc.)
    CME = "cme"             # CME Group (US futures)
    GENERIC = "generic"     # Generic/unknown market


class FrequencyType(Enum):
    """Supported data frequencies."""
    DAILY = "daily"         # Interday (1 bar per day)
    MINUTE = "minute"       # Intraday (1-min to 1-hour bars)


# =============================================================================
# Column Definitions by Tier
# =============================================================================

# TIER 1: Core columns required for ALL data
CORE_COLUMNS: Dict[str, str] = {
    'date': 'datetime64[ns]',       # Trading date (normalized to midnight)
    'open': 'float64',              # Opening price
    'high': 'float64',              # High price
    'low': 'float64',               # Low price
    'close': 'float64',             # Closing price
    'volume': 'float64',            # Trading volume (float for crypto fractional)
}

# TIER 2: Frequency-specific columns
INTRADAY_COLUMNS: Dict[str, str] = {
    'datetime': 'datetime64[ns]',   # Full timestamp (date + time)
    'trading_date': 'object',       # Trading date as YYYYMMDD string (for grouping)
}

# Session columns for markets with trading sessions (SHFE, CME)
SESSION_COLUMNS: Dict[str, str] = {
    'session_phase': 'object',      # Session phase (night, morning, afternoon, etc.)
    'is_tradeable': 'bool',         # Whether trading is allowed in this bar
}

# TIER 3: Market-specific columns
FUTURES_COLUMNS: Dict[str, str] = {
    'contract': 'object',           # Contract identifier (e.g., 'al2403', 'ESH24')
    'contract_expiry': 'int64',     # Expiry date as YYYYMMDD integer
    'open_interest': 'float64',     # Open interest
    'settlement': 'float64',        # Settlement price
    'prev_close': 'float64',        # Previous close
    'prev_settlement': 'float64',   # Previous settlement
    'turnover': 'float64',          # Trading turnover (value)
}

CRYPTO_COLUMNS: Dict[str, str] = {
    'symbol': 'object',             # Trading pair (e.g., 'BTCUSDT')
    'quote_volume': 'float64',      # Volume in quote currency
    'trades': 'int64',              # Number of trades
    'taker_buy_volume': 'float64',  # Taker buy volume
}

# TIER 4: Optional/derived columns
DERIVED_COLUMNS: Dict[str, str] = {
    'returns': 'float64',           # Log returns: log(close/prev_close)
    'range': 'float64',             # High - Low
    'body': 'float64',              # abs(close - open)
    'upper_shadow': 'float64',      # High - max(open, close)
    'lower_shadow': 'float64',      # min(open, close) - Low
}


# =============================================================================
# Schema Configuration by Market
# =============================================================================

@dataclass
class SchemaConfig:
    """Configuration for a specific market/frequency combination."""
    market: MarketType
    frequency: FrequencyType

    # Column requirements
    required_columns: Set[str] = field(default_factory=set)
    optional_columns: Set[str] = field(default_factory=set)

    # Validation rules
    has_sessions: bool = False          # Has trading sessions (breaks)
    has_expiry: bool = False            # Has contract expiry
    is_24_7: bool = False               # 24/7 trading (crypto)

    def __post_init__(self):
        """Build column sets based on market/frequency."""
        # Start with core columns
        self.required_columns = set(CORE_COLUMNS.keys())

        # Add frequency-specific columns
        if self.frequency == FrequencyType.MINUTE:
            self.required_columns.update(INTRADAY_COLUMNS.keys())

            # Session columns for non-24/7 markets
            if not self.is_24_7:
                self.optional_columns.update(SESSION_COLUMNS.keys())

        # Add market-specific columns
        if self.market in (MarketType.SHFE, MarketType.CME):
            self.optional_columns.update(FUTURES_COLUMNS.keys())
            self.has_expiry = True
            self.has_sessions = True

        elif self.market == MarketType.CRYPTO:
            self.optional_columns.update(CRYPTO_COLUMNS.keys())
            self.is_24_7 = True

        # Derived columns are always optional
        self.optional_columns.update(DERIVED_COLUMNS.keys())


# Pre-defined configurations for common scenarios
SCHEMA_CONFIGS: Dict[str, SchemaConfig] = {
    'shfe_daily': SchemaConfig(
        market=MarketType.SHFE,
        frequency=FrequencyType.DAILY,
        has_sessions=False,  # Daily bars don't need session info
        has_expiry=True,
    ),
    'shfe_minute': SchemaConfig(
        market=MarketType.SHFE,
        frequency=FrequencyType.MINUTE,
        has_sessions=True,
        has_expiry=True,
    ),
    'crypto_daily': SchemaConfig(
        market=MarketType.CRYPTO,
        frequency=FrequencyType.DAILY,
        is_24_7=True,
    ),
    'crypto_minute': SchemaConfig(
        market=MarketType.CRYPTO,
        frequency=FrequencyType.MINUTE,
        is_24_7=True,
    ),
}


# =============================================================================
# Standard Schema Class
# =============================================================================

class StandardSchema:
    """
    Standard market data schema with validation.

    This class defines the contract between data_pipeline output and
    indicators module input. All data must pass validation before
    being consumed by downstream modules.

    Usage:
        >>> from echolon.data_pipeline.schemas import StandardSchema
        >>>
        >>> # Create schema for SHFE daily data
        >>> schema = StandardSchema(market='shfe', frequency='daily')
        >>>
        >>> # Validate DataFrame
        >>> is_valid, errors = schema.validate(df)
        >>>
        >>> # Get required columns
        >>> required = schema.get_required_columns()
    """

    def __init__(
        self,
        market: str = 'shfe',
        frequency: str = 'daily',
    ):
        """
        Initialize schema for specific market/frequency.

        Args:
            market: Market type ('shfe', 'crypto', 'cme', 'generic')
            frequency: Data frequency ('daily', 'minute')
        """
        self.market = MarketType(market.lower())
        self.frequency = FrequencyType(frequency.lower())

        # Get or create config
        config_key = f"{market.lower()}_{frequency.lower()}"
        if config_key in SCHEMA_CONFIGS:
            self.config = SCHEMA_CONFIGS[config_key]
        else:
            self.config = SchemaConfig(
                market=self.market,
                frequency=self.frequency,
            )

    def get_required_columns(self) -> List[str]:
        """Get list of required columns."""
        return sorted(list(self.config.required_columns))

    def get_optional_columns(self) -> List[str]:
        """Get list of optional columns."""
        return sorted(list(self.config.optional_columns))

    def get_all_columns(self) -> List[str]:
        """Get all recognized columns (required + optional)."""
        return sorted(list(
            self.config.required_columns | self.config.optional_columns
        ))

    def get_column_types(self) -> Dict[str, str]:
        """Get column type mapping for all columns."""
        types = {}
        types.update(CORE_COLUMNS)
        types.update(INTRADAY_COLUMNS)
        types.update(SESSION_COLUMNS)
        types.update(FUTURES_COLUMNS)
        types.update(CRYPTO_COLUMNS)
        types.update(DERIVED_COLUMNS)
        return types

    def validate(
        self,
        df: pd.DataFrame,
        strict: bool = False,
    ) -> tuple[bool, List[str]]:
        """
        Validate DataFrame against schema.

        Args:
            df: DataFrame to validate
            strict: If True, fail on warnings too

        Returns:
            Tuple of (is_valid, list of error/warning messages)
        """
        errors = []
        warnings = []

        # Check required columns
        missing_required = self.config.required_columns - set(df.columns)
        if missing_required:
            errors.append(f"Missing required columns: {sorted(missing_required)}")

        # Check column types for existing columns
        column_types = self.get_column_types()
        for col in df.columns:
            if col in column_types:
                expected_type = column_types[col]
                actual_type = str(df[col].dtype)

                # Allow compatible types
                if not self._types_compatible(actual_type, expected_type):
                    warnings.append(
                        f"Column '{col}' has type '{actual_type}', "
                        f"expected '{expected_type}'"
                    )

        # Check data integrity
        integrity_errors = self._check_data_integrity(df)
        errors.extend(integrity_errors)

        # Determine validity
        is_valid = len(errors) == 0
        if strict:
            is_valid = is_valid and len(warnings) == 0

        # Combine messages
        all_messages = [f"ERROR: {e}" for e in errors]
        all_messages.extend([f"WARNING: {w}" for w in warnings])

        return is_valid, all_messages

    def _types_compatible(self, actual: str, expected: str) -> bool:
        """Check if actual type is compatible with expected type."""
        # Exact match
        if actual == expected:
            return True

        # Float compatibility
        if 'float' in expected and 'float' in actual:
            return True
        if 'float' in expected and 'int' in actual:
            return True  # int can be used as float

        # Int compatibility
        if 'int' in expected and 'int' in actual:
            return True

        # Datetime compatibility
        if 'datetime' in expected and 'datetime' in actual:
            return True

        # Object/string compatibility
        if expected == 'object' and actual in ('object', 'string', 'str'):
            return True

        return False

    def _check_data_integrity(self, df: pd.DataFrame) -> List[str]:
        """Check data integrity rules."""
        errors = []

        if df.empty:
            errors.append("DataFrame is empty")
            return errors

        # OHLC relationship: high >= low
        if 'high' in df.columns and 'low' in df.columns:
            invalid_hl = (df['high'] < df['low']).sum()
            if invalid_hl > 0:
                errors.append(f"{invalid_hl} rows have high < low")

        # OHLC relationship: high >= open, close
        if all(col in df.columns for col in ['high', 'open', 'close']):
            invalid_ho = (df['high'] < df['open']).sum()
            invalid_hc = (df['high'] < df['close']).sum()
            if invalid_ho > 0:
                errors.append(f"{invalid_ho} rows have high < open")
            if invalid_hc > 0:
                errors.append(f"{invalid_hc} rows have high < close")

        # OHLC relationship: low <= open, close
        if all(col in df.columns for col in ['low', 'open', 'close']):
            invalid_lo = (df['low'] > df['open']).sum()
            invalid_lc = (df['low'] > df['close']).sum()
            if invalid_lo > 0:
                errors.append(f"{invalid_lo} rows have low > open")
            if invalid_lc > 0:
                errors.append(f"{invalid_lc} rows have low > close")

        # Positive prices
        for col in ['open', 'high', 'low', 'close']:
            if col in df.columns:
                negative_count = (df[col] <= 0).sum()
                if negative_count > 0:
                    errors.append(f"{negative_count} rows have non-positive {col}")

        # Non-negative volume
        if 'volume' in df.columns:
            negative_vol = (df['volume'] < 0).sum()
            if negative_vol > 0:
                errors.append(f"{negative_vol} rows have negative volume")

        # Check for NaN in critical columns
        critical_columns = ['date', 'close']
        for col in critical_columns:
            if col in df.columns:
                nan_count = df[col].isna().sum()
                if nan_count > 0:
                    errors.append(f"{nan_count} NaN values in critical column '{col}'")

        return errors

    def conform(
        self,
        df: pd.DataFrame,
        fill_missing: bool = True,
    ) -> pd.DataFrame:
        """
        Conform DataFrame to schema by adding missing optional columns.

        Args:
            df: Input DataFrame
            fill_missing: Fill missing OHLC values using close price

        Returns:
            Conformed DataFrame
        """
        result = df.copy()

        # Fill missing OHLC values
        if fill_missing and 'close' in result.columns:
            for col in ['open', 'high', 'low']:
                if col in result.columns:
                    result[col] = result[col].fillna(result['close'])

        # Add trading_date from date if missing (for intraday)
        if (self.frequency == FrequencyType.MINUTE and
            'trading_date' not in result.columns and
            'date' in result.columns):
            result['trading_date'] = pd.to_datetime(
                result['date']
            ).dt.strftime('%Y%m%d')

        # Ensure correct column order
        ordered_cols = []
        for col in self.get_all_columns():
            if col in result.columns:
                ordered_cols.append(col)

        # Add remaining columns not in schema
        for col in result.columns:
            if col not in ordered_cols:
                ordered_cols.append(col)

        return result[ordered_cols]

    def get_schema_info(self) -> Dict[str, Any]:
        """Get schema information as dictionary."""
        return {
            'market': self.market.value,
            'frequency': self.frequency.value,
            'required_columns': self.get_required_columns(),
            'optional_columns': self.get_optional_columns(),
            'has_sessions': self.config.has_sessions,
            'has_expiry': self.config.has_expiry,
            'is_24_7': self.config.is_24_7,
        }


# =============================================================================
# Convenience Functions
# =============================================================================

def get_schema(market: str, frequency: str) -> StandardSchema:
    """
    Get schema for market/frequency combination.

    Args:
        market: Market type ('shfe', 'crypto', 'cme')
        frequency: Data frequency ('daily', 'minute')

    Returns:
        StandardSchema instance
    """
    return StandardSchema(market=market, frequency=frequency)


def validate_dataframe(
    df: pd.DataFrame,
    market: str = 'shfe',
    frequency: str = 'daily',
    strict: bool = False,
) -> tuple[bool, List[str]]:
    """
    Validate DataFrame against standard schema.

    Args:
        df: DataFrame to validate
        market: Market type
        frequency: Data frequency
        strict: Fail on warnings too

    Returns:
        Tuple of (is_valid, messages)
    """
    schema = StandardSchema(market=market, frequency=frequency)
    return schema.validate(df, strict=strict)


def get_missing_columns(
    df: pd.DataFrame,
    market: str = 'shfe',
    frequency: str = 'daily',
) -> List[str]:
    """
    Get list of missing required columns.

    Args:
        df: DataFrame to check
        market: Market type
        frequency: Data frequency

    Returns:
        List of missing column names
    """
    schema = StandardSchema(market=market, frequency=frequency)
    required = set(schema.get_required_columns())
    present = set(df.columns)
    return sorted(list(required - present))


# =============================================================================
# For backwards compatibility with ohlcv.py
# =============================================================================

# Re-export old names for compatibility
OHLCV_COLUMNS = list(CORE_COLUMNS.keys())
COLUMN_TYPES = {**CORE_COLUMNS, **FUTURES_COLUMNS}


class OHLCVSchema:
    """
    Legacy OHLCV schema for backwards compatibility.

    Prefer using StandardSchema for new code.
    """
    REQUIRED = list(CORE_COLUMNS.keys())
    OPTIONAL = list(FUTURES_COLUMNS.keys())
    TYPES = COLUMN_TYPES

    @classmethod
    def validate(cls, df: pd.DataFrame) -> bool:
        """Validate DataFrame has required columns."""
        missing = set(cls.REQUIRED) - set(df.columns)
        return len(missing) == 0

    @classmethod
    def get_missing_columns(cls, df: pd.DataFrame) -> List[str]:
        """Get list of missing required columns."""
        return list(set(cls.REQUIRED) - set(df.columns))
