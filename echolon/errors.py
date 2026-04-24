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
    "DAT-002": {
        "class": DataError,
        "what": "State file is corrupt or unreadable JSON",
        "why": (
            "A live deploy reads strategy_state.json to resume position and "
            "cycle counters. A truncated or malformed file silently defaults "
            "to an empty state, losing position information mid-session."
        ),
        "fix_template": (
            "Inspect the state file and either repair it or delete it to "
            "cold-start:\n"
            "  path:       {path}\n"
            "  parse_error: {error}"
        ),
    },
    "DAT-003": {
        "class": DataError,
        "what": "Main contract data file not found for instrument",
        "why": (
            "Echolon resolves the main contract per trading date from "
            "raw_data_dir/{exchange}/{symbol}/main_contract.csv. Without "
            "this file, contract rollover and live trading cannot proceed."
        ),
        "fix_template": (
            "Run the data pipeline once to populate main_contract.csv, "
            "or pass an explicit raw_data_dir pointing at a populated tree.\n"
            "  expected:  {path}\n"
            "  symbol:    {symbol}"
        ),
    },
    "DAT-004": {
        "class": DataError,
        "what": "Trading calendar is empty after generation",
        "why": (
            "Calendar generation received zero valid rows. Either the input "
            "data has no date column, all dates are outside the requested "
            "range, or the source file is empty."
        ),
        "fix_template": (
            "Verify the upstream source has dated rows in the requested range:\n"
            "  market:      {market}\n"
            "  instrument:  {instrument}\n"
            "  start_date:  {start_date}\n"
            "  end_date:    {end_date}\n"
            "  rows_seen:   {rows_seen}"
        ),
    },
    "IND-003": {
        "class": IndicatorError,
        "what": "Indicator column produced more NaN than warmup requires",
        "why": (
            "The indicator was requested with a period that exceeds the "
            "available bar history. More than the warmup-plus-some-headroom "
            "rows are NaN, which silently breaks downstream strategies that "
            "compare the column against thresholds."
        ),
        "fix_template": (
            "Either shorten the indicator period or extend the backtest "
            "start date to allow warmup:\n"
            "  indicator:  {indicator}\n"
            "  period:     {period}\n"
            "  rows:       {rows}\n"
            "  nan_rows:   {nan_rows}\n"
            "  nan_ratio:  {nan_ratio:.1%}"
        ),
    },
    "IND-004": {
        "class": IndicatorError,
        "what": "Regime optimizer returned a degenerate best-trial",
        "why": (
            "Every Optuna trial violated at least one hard constraint "
            "(min_ranging_pct / min_trending_pct / etc.), so the best-trial "
            "is the first-evaluated arbitrary trial, not a validated result. "
            "Deploying these params is unsafe."
        ),
        "fix_template": (
            "Loosen constraints in RegimeOptimizerConfig, or increase the "
            "historical window so the optimizer has enough regime-segments "
            "to satisfy constraints:\n"
            "  n_trials:          {n_trials}\n"
            "  trials_rejected:   {trials_rejected}\n"
            "  rejected_reasons:  {rejected_reasons}"
        ),
    },
    "IND-005": {
        "class": IndicatorError,
        "what": "Calculator received a DataFrame without a required column",
        "why": (
            "Indicator calculators have explicit column contracts (e.g., a "
            "session-phase indicator requires 'datetime' and 'trading_date'). "
            "Running the calculator on a DataFrame missing those columns "
            "silently produces all-NaN output in the best case, junk values "
            "in the worst."
        ),
        "fix_template": (
            "Ensure the input DataFrame has all required columns before "
            "calling the calculator:\n"
            "  calculator:         {calculator}\n"
            "  missing_column:     {missing_column}\n"
            "  required_columns:   {required_columns}\n"
            "  present_columns:    {present_columns}"
        ),
    },
    "BT-001": {
        "class": EchelonError,
        "what": "Strategy.on_bar() raised an exception",
        "why": (
            "A strategy's entry/exit/risk/sizer component raised during a "
            "bar-level call. The exception was caught by the engine so the "
            "backtest could stop cleanly; the strategy code is the likely root cause."
        ),
        "fix_template": (
            "Open {file} at the component that raised and reproduce with "
            "the context below:\n"
            "  bar_index:       {bar_index}\n"
            "  trading_date:    {trading_date}\n"
            "  contract:        {contract}\n"
            "  position_size:   {position_size}\n"
            "  exception:       {exception_repr}"
        ),
    },
    "BT-002": {
        "class": EchelonError,
        "what": "Backtest produced zero trades",
        "why": (
            "The strategy ran through the configured period without firing "
            "a single entry. Common causes: entry conditions never met, "
            "filters block every signal, risk manager blocks every order."
        ),
        "fix_template": (
            "Inspect entry/filter/risk diagnostics printed above this error:\n"
            "  bars_processed:          {bars_processed}\n"
            "  entry_signals_generated: {entry_signals_generated}\n"
            "  entry_signals_blocked:   {entry_signals_blocked}\n"
            "  risk_blocks:             {risk_blocks}\n"
            "See docs/errors/BT-002.md for the decision tree."
        ),
    },
    "BT-003": {
        "class": EchelonError,
        "what": "Optuna trial violated a hard constraint",
        "why": (
            "The trial's param set produced regime metrics outside the "
            "viability bounds configured in RegimeOptimizerConfig. The "
            "trial's score is clamped to 0.0 so it will not be selected."
        ),
        "fix_template": (
            "Widen the constraint or the param range that triggered this:\n"
            "  trial_number:   {trial_number}\n"
            "  constraint:     {constraint}\n"
            "  required:       {required}\n"
            "  actual:         {actual}\n"
            "  params:         {params}"
        ),
    },
    "LIV-001": {
        "class": EchelonError,
        "what": "Broker connection unavailable",
        "why": (
            "The QMT/CCXT client lost connection or failed to initialize. "
            "Trading is halted; no orders will be submitted until the "
            "connection is restored."
        ),
        "fix_template": (
            "Restore the broker connection and restart the runner:\n"
            "  platform:     {platform}\n"
            "  account_id:   {account_id}\n"
            "  error:        {error}"
        ),
    },
    "LIV-002": {
        "class": EchelonError,
        "what": "Order rejected by broker",
        "why": (
            "The broker rejected an order. Common causes: price outside the "
            "day's range, insufficient margin, invalid contract code, "
            "direction/size mismatch."
        ),
        "fix_template": (
            "Inspect the rejected order and broker response:\n"
            "  contract:       {contract}\n"
            "  direction:      {direction}\n"
            "  price:          {price}\n"
            "  size:           {size}\n"
            "  broker_status:  {broker_status}\n"
            "  broker_message: {broker_message}"
        ),
    },
    "WFA-001": {
        "class": EchelonError,
        "what": "WFA pipeline produced zero valid trials across all windows",
        "why": (
            "Every walk-forward window ran its Optuna optimization but "
            "produced no successful trials. This is almost always a strategy "
            "or configuration bug rather than a market-fit issue — the same "
            "error is repeating on every trial. Per-window "
            "trial_failure_summary.json artifacts carry the structured root "
            "cause for each window."
        ),
        "fix_template": (
            "Inspect per-window trial_failure_summary.json artifacts:\n"
            "  n_windows:           {n_windows}\n"
            "  reason:              {reason}\n"
            "  per_window_artifacts: {suggestion}"
        ),
    },
    "LIV-003": {
        "class": EchelonError,
        "what": "QMT async callback delivered an error",
        "why": (
            "The miniQMT xtconstant callback for order/trade status indicated "
            "a failure outcome. The callback thread logs this but the main "
            "loop needs to translate it for the LLM agent monitoring the run."
        ),
        "fix_template": (
            "Translate the QMT status code and follow broker-specific remediation:\n"
            "  seq_id:       {seq_id}\n"
            "  qmt_status:   {qmt_status}\n"
            "  echo_status:  {echo_status}\n"
            "  raw:          {raw}"
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
