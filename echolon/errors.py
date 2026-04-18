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


# =============================================================================
# Error Catalog Registry
# =============================================================================

ERROR_CATALOG: dict[str, dict] = {
    "VAL-001": {
        "class": ValidationError,
        "what": "Missing required field in component output",
        "why": (
            "Echolon component contracts require all fields for downstream "
            "trade logging, regime evaluation, and backtest analysis."
        ),
        "fix_template": (
            "In {file}:{method}, add missing fields to the output object:\n"
            "  missing fields: {missing}\n"
            "See docs/COMPONENT_GUIDE.md for the full contract."
        ),
    },
    "VAL-002": {
        "class": ValidationError,
        "what": "Invalid enum value in signal field",
        "why": "Signal values must be 'LONG', 'SHORT', or 'HOLD'.",
        "fix_template": (
            "In {file}:{method}, use a valid signal value.\n"
            "  got: {got}\n"
            "  expected: 'LONG' | 'SHORT' | 'HOLD'"
        ),
    },
    "VAL-003": {
        "class": ValidationError,
        "what": "Component class signature mismatch",
        "why": (
            "Component classes must accept (trading_engine, **params) and "
            "call super().__init__(trading_engine, **params)."
        ),
        "fix_template": (
            "In {file}, {class_name}.__init__ must have signature:\n"
            "  def __init__(self, trading_engine, **params):\n"
            "      super().__init__(trading_engine, **params)"
        ),
    },
    "CFG-001": {
        "class": ConfigError,
        "what": "end_date before start_date",
        "why": "Backtest date range is invalid.",
        "fix_template": (
            "Set end_date to a date after start_date.\n"
            "  start_date: {start_date}\n"
            "  end_date:   {end_date}"
        ),
    },
    "CFG-002": {
        "class": ConfigError,
        "what": "Required directory does not exist",
        "why": "Echolon cannot read from a path that doesn't exist.",
        "fix_template": (
            "Create the directory or update your config:\n"
            "  missing path: {path}\n"
            "  field:        {field}"
        ),
    },
    "STR-001": {
        "class": StrategyStructureError,
        "what": "Strategy directory missing required file",
        "why": "Every Echolon strategy needs 7 files for the loader to work.",
        "fix_template": (
            "Add the missing file to {strategy_dir}:\n"
            "  missing: {missing_files}\n"
            "See `echolon init-strategy --template minimal` for a working example."
        ),
    },
    "STR-002": {
        "class": StrategyStructureError,
        "what": "Required class not found in file",
        "why": (
            "Echolon loads components by exact class name. Class name must "
            "match the file's expected export."
        ),
        "fix_template": (
            "In {file}, rename the class to {expected_class}.\n"
            "Found: {found_classes}"
        ),
    },
    "STR-003": {
        "class": StrategyStructureError,
        "what": "Required method not implemented",
        "why": "Component base classes require specific abstract methods.",
        "fix_template": (
            "In {file}.{class_name}, implement method: {missing_method}\n"
            "See docs/COMPONENT_GUIDE.md for signatures."
        ),
    },
    "IND-001": {
        "class": IndicatorError,
        "what": "Indicator name casing mismatch between code and JSON",
        "why": (
            "Indicator column names are lowercase in pre-computed data. "
            "Using uppercase in code causes silent KeyError or NaN at runtime."
        ),
        "fix_template": (
            "Change code to use lowercase indicator name:\n"
            "  code uses: {code_name}\n"
            "  should be: {json_name}\n"
            "See docs/PATTERNS.md#indicators for naming rules."
        ),
    },
    "IND-002": {
        "class": IndicatorError,
        "what": "Indicator referenced in code but not declared in JSON",
        "why": (
            "strategy_indicator_list.json declares which indicators to "
            "pre-compute. Code must only use declared indicators."
        ),
        "fix_template": (
            "Add {indicator} to strategy_indicator_list.json, or remove its "
            "usage from {file}:{line}."
        ),
    },
    "PRM-001": {
        "class": ParameterError,
        "what": "Missing 'printlog' key in component params",
        "why": (
            "Parameter framework requires 'printlog': False in every "
            "component sub-dict. Omitting it causes validation to fail."
        ),
        "fix_template": (
            "In {file}:{function}, add 'printlog': False to {component_key}:\n"
            "  params[{component_key!r}] = {{'printlog': False, ...}}"
        ),
    },
    "PRM-002": {
        "class": ParameterError,
        "what": "Strategy params structure mismatch",
        "why": (
            "strategy_params.py must export DEFAULT_PARAMS as a dict with "
            "keys: entry_params, exit_params, risk_params, sizer_params."
        ),
        "fix_template": (
            "In {file}, DEFAULT_PARAMS must have shape:\n"
            "  {{'entry_params': {{...}}, 'exit_params': {{...}}, \n"
            "   'risk_params': {{...}}, 'sizer_params': {{...}}}}\n"
            "Missing keys: {missing_keys}"
        ),
    },
    "DAT-001": {
        "class": DataError,
        "what": "Required OHLCV file not found",
        "why": "Echolon needs market data to run a backtest.",
        "fix_template": (
            "Expected file at: {path}\n"
            "Run data pipeline first or update market_data_dir in your config."
        ),
    },
}


def raise_error(code: str, **context_vars: Any) -> None:
    """Raise an EchelonError by code with context formatted into fix template."""
    entry = ERROR_CATALOG[code]
    try:
        fix = entry["fix_template"].format(**context_vars)
    except KeyError:
        fix = entry["fix_template"]
    raise entry["class"](
        code=code,
        what=entry["what"],
        why=entry["why"],
        fix=fix,
        context=dict(context_vars),
        docs_url=f"https://echolon.dev/docs/errors/{code}",
    )
