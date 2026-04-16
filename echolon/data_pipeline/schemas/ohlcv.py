"""
OHLCV Data Schema (Legacy Compatibility)
========================================

This module re-exports from standard_schema.py for backwards compatibility.
For new code, use StandardSchema directly:

    from echolon.data_pipeline.schemas import StandardSchema

    schema = StandardSchema(market='shfe', frequency='daily')
    is_valid, errors = schema.validate(df)
"""

from .standard_schema import (
    # Legacy exports
    OHLCV_COLUMNS,
    COLUMN_TYPES,
    OHLCVSchema,
    # New exports (for migration)
    CORE_COLUMNS,
    FUTURES_COLUMNS,
    INTRADAY_COLUMNS,
    StandardSchema,
    get_schema,
    validate_dataframe,
    get_missing_columns,
)

# For backwards compatibility
FUTURES_COLUMNS_LIST = list(FUTURES_COLUMNS.keys())

__all__ = [
    # Legacy
    'OHLCV_COLUMNS',
    'FUTURES_COLUMNS',
    'COLUMN_TYPES',
    'OHLCVSchema',
    # New
    'StandardSchema',
    'get_schema',
    'validate_dataframe',
    'get_missing_columns',
]
