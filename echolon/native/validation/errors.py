"""Echolon error hierarchy and catalog."""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class EchelonError(Exception):
    """Base class for all Echolon validation errors."""
    code: str
    what: str
    why: str
    fix: str
    context: dict[str, Any] = field(default_factory=dict)
    docs_url: str = ""

    def __str__(self) -> str:
        return (
            f"\n[{self.code}] {self.what}\n"
            f"  Why:     {self.why}\n"
            f"  Fix:     {self.fix}\n"
            f"  Context: {self.context}\n"
            f"  Docs:    {self.docs_url}\n"
        )


@dataclass
class ValidationError(EchelonError):
    """Validation / type errors (VAL-xxx)."""


@dataclass
class ConfigError(EchelonError):
    """Config errors (CFG-xxx)."""


@dataclass
class StrategyStructureError(EchelonError):
    """Strategy directory structure errors (STR-xxx)."""


@dataclass
class IndicatorError(EchelonError):
    """Indicator name / casing errors (IND-xxx)."""


@dataclass
class ParameterError(EchelonError):
    """Parameter framework errors (PRM-xxx)."""


@dataclass
class DataError(EchelonError):
    """Data loading / file errors (DAT-xxx)."""
