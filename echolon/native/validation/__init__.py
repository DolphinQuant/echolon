"""Validation package — errors and validators for AI-native Echolon."""

from echolon.errors import (
    ERROR_CATALOG,
    ConfigError,
    DataError,
    EchelonError,
    IndicatorError,
    ParameterError,
    StrategyStructureError,
    ValidationError,
    raise_error,
)
from echolon.native.validation.indicator_validator import validate_indicator_names
from echolon.native.validation.strategy_validator import REQUIRED_FILES, validate_strategy_dir

__all__ = [
    "ERROR_CATALOG",
    "EchelonError",
    "ValidationError",
    "ConfigError",
    "StrategyStructureError",
    "IndicatorError",
    "ParameterError",
    "DataError",
    "REQUIRED_FILES",
    "raise_error",
    "validate_strategy_dir",
    "validate_indicator_names",
]
