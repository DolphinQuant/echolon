# LLM-Debuggability Migration Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn echolon's ~139 bare `raise` sites and diffuse logging into a structured, LLM-navigable error/observability surface so AI agents coding strategies against echolon can self-debug from exceptions + logs alone.

**Architecture:** Six sequential phases that can each ship independently to `master`. Phase 0 repairs `backtest/logging_utils.py` (~60 LOC, unblocks Phase 1 semantics). Phase 1 fills the catalog and wires the top 40 bare raises library-wide. Phase 2 eliminates three load-bearing silent-fallback anti-patterns. Phase 3 adds opt-in JSON-lines logging and per-module DEBUG gates. Phase 4 concentrates pre-flight validation in `strategy/loader.py`. **Phase 4B closes the four remaining gaps on an LLM strategy-author's hot path**: IND-001 (indicator casing mismatch), VAL-001 + `extra='forbid'` on signal outputs, new IND-005 (missing OHLCV column in calculators), DAT-001 wiring in `ohlcv_loader`. Phase 5 publishes a stable docs URL scheme backing the existing `docs_url` field on `EchelonError`.

**Tech Stack:** Python 3.11+, `EchelonError` dataclass at `echolon/errors.py`, stdlib `logging` + `contextvars`, pytest, `ast.parse` for AST regression tests.

---

## File Structure

**New files:**
- `echolon/_internal/structured_logging.py` — optional JSON-lines handler + per-module DEBUG gate, env-var-gated.
- `tests/test_error_catalog.py` — AST regression: no bare `raise ValueError/RuntimeError/FileNotFoundError` in migrated-subsystem allowlist.
- `tests/_internal/test_structured_logging.py` — JSON-lines format, per-module DEBUG resolution.
- `docs/errors/{code}.md` — one file per catalog code (Phase 5).

**Modified files (one commit per logical group):**

| Phase | Files |
|---|---|
| 0 | `echolon/backtest/logging_utils.py`, `tests/backtest/test_logging_utils.py` (new) |
| 1 | `echolon/errors.py` (add codes), consumers across data/indicators/backtest/live/strategy (~40 raise sites) |
| 2 | `echolon/data/loaders/session_availability_loader.py`, `echolon/indicators/engine/processor.py`, `echolon/indicators/optimization/interday_regime_optimizer.py` |
| 3 | `echolon/_internal/structured_logging.py` (new), high-volume loggers in `processor.py`, `interday_regime_optimizer.py`, `backtest/engine/hooks/contract_aware/broker.py` |
| 4 | `echolon/strategy/loader.py`, `echolon/strategy/parameter_architecture.py`, `echolon/strategy/schemas.py`, `echolon/strategy/component.py` |
| 4B | `echolon/strategy/preflight.py` (extend), `echolon/strategy/schemas.py` (tighten), `echolon/data/loaders/ohlcv_loader.py`, `echolon/indicators/calculators/{interday,intraday}/*.py` (column validators), `echolon/errors.py` (add IND-005) |
| 5 | `docs/errors/*.md` (one per code), `docs/CONFIG_REFERENCE.md` cross-links |

---

## Migration branch + commit discipline

All phases land on a single branch. Each phase's final commit is a merge-ready checkpoint; `master` can fast-forward to any phase boundary.

```bash
cd /home/yzj/projects/quantitive_trading/echolon
git checkout -b llm-debuggability-migration
git commit --allow-empty -m "chore: start llm-debuggability migration"
```

One commit per task. No commits that leave the tree red.

---

# PHASE 0 — Repair `logging_utils.py` hygiene

**Rationale:** Three defects in `logging_utils.py` undermine every downstream phase:
1. Stale `modules.quant_engine.*` logger-name lists (post-reorg, these don't exist) — `optimization` mode never actually silences anything.
2. `log_workflow_success` and `log_result_summary` use `logger.critical(...)` as a workaround to bypass the optimization-mode WARNING filter — which corrupts CRITICAL's "something is on fire" semantics.
3. Module-level `_current_context: RunContext = "debug"` mutable global — Optuna parallel trials race on it.

Phase 0 is ~60 LOC touching one file + one test file. Ship first.

## Task P0.1 — Introduce a `RESULT` custom log level

**Files:**
- Modify: `echolon/backtest/logging_utils.py`
- Test: `tests/backtest/test_logging_utils.py` (new)

- [ ] **Step 1: Create the test dir and write the failing test**

```bash
mkdir -p /home/yzj/projects/quantitive_trading/echolon/tests/backtest
```

Create `tests/backtest/test_logging_utils.py`:

```python
"""Regression: logging_utils uses a custom RESULT level, not CRITICAL, for successes."""
import logging

from echolon.backtest import logging_utils


def test_result_level_is_defined():
    assert hasattr(logging_utils, "RESULT")
    assert logging_utils.RESULT == 35  # between WARNING (30) and ERROR (40)
    assert logging.getLevelName(35) == "RESULT"


def test_log_workflow_success_uses_result_level(caplog):
    with caplog.at_level(logging_utils.RESULT, logger="echolon.backtest.logging_utils"):
        logging_utils.log_workflow_success(
            context="debug", workflow="Backtest", sharpe=1.23
        )
    assert any(r.levelno == logging_utils.RESULT for r in caplog.records)
    assert not any(r.levelno == logging.CRITICAL for r in caplog.records)


def test_log_result_summary_uses_result_level(caplog):
    with caplog.at_level(logging_utils.RESULT, logger="echolon.backtest.logging_utils"):
        logging_utils.log_result_summary(
            context="debug",
            workflow="Backtest",
            sharpe=1.0,
            total_return=10.0,
            max_drawdown=5.0,
            num_trades=42,
        )
    assert any(r.levelno == logging_utils.RESULT for r in caplog.records)
    assert not any(r.levelno == logging.CRITICAL for r in caplog.records)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/backtest/test_logging_utils.py -v`

Expected: FAIL — `AttributeError: module 'echolon.backtest.logging_utils' has no attribute 'RESULT'`.

- [ ] **Step 3: Add RESULT level + register with stdlib**

Edit `echolon/backtest/logging_utils.py`. After `import logging` near the top, add:

```python
# Custom log level between WARNING (30) and ERROR (40). Used for milestone
# events ("backtest finished", "trial result") that must be visible in
# optimization mode without abusing CRITICAL (reserved for "stop the process").
RESULT = 35
logging.addLevelName(RESULT, "RESULT")
```

- [ ] **Step 4: Convert the CRITICAL calls to RESULT**

In `log_workflow_success` (~line 216), change `logger.critical(msg)` → `logger.log(RESULT, msg)`.

In `log_result_summary` (~line 292), change `logger.critical(f"[...] RESULT SUMMARY | ...")` → `logger.log(RESULT, f"[...] RESULT SUMMARY | ...")`.

`log_workflow_failure` keeps `logger.critical(...)` — that IS a failure.

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/backtest/test_logging_utils.py::test_result_level_is_defined tests/backtest/test_logging_utils.py::test_log_workflow_success_uses_result_level tests/backtest/test_logging_utils.py::test_log_result_summary_uses_result_level -v`

Expected: 3 passed.

- [ ] **Step 6: Commit**

```bash
git add echolon/backtest/logging_utils.py tests/backtest/test_logging_utils.py
git commit -m "feat(logging): add RESULT level, stop abusing CRITICAL for successes"
```

---

## Task P0.2 — Make `log_workflow_failure` accept an Exception

**Files:**
- Modify: `echolon/backtest/logging_utils.py`
- Modify: `tests/backtest/test_logging_utils.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/backtest/test_logging_utils.py`:

```python
def test_log_workflow_failure_accepts_exception_and_records_traceback(caplog):
    try:
        raise ValueError("boom")
    except ValueError as exc:
        logging_utils.log_workflow_failure(
            context="debug", workflow="Backtest", error=exc
        )
    # Record exists and has exc_info (traceback captured)
    records = [r for r in caplog.records if r.levelno == logging.CRITICAL]
    assert records, "CRITICAL-level record expected"
    assert records[-1].exc_info is not None
    assert records[-1].exc_info[0] is ValueError


def test_log_workflow_failure_accepts_string_backcompat(caplog):
    logging_utils.log_workflow_failure(
        context="debug", workflow="Backtest", error="simple string"
    )
    records = [r for r in caplog.records if r.levelno == logging.CRITICAL]
    assert records
    assert "simple string" in records[-1].message
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/backtest/test_logging_utils.py::test_log_workflow_failure_accepts_exception_and_records_traceback -v`

Expected: FAIL — `exc_info is None` (current impl takes only strings).

- [ ] **Step 3: Update the signature + body**

Replace `log_workflow_failure` in `echolon/backtest/logging_utils.py`:

```python
def log_workflow_failure(
    context: RunContext,
    workflow: str,
    error: Exception | str,
) -> None:
    """
    Log workflow failure. Accepts either an exception (preferred — traceback
    is captured automatically via exc_info) or a plain string for legacy
    callers.

    Format: "[CONTEXT] Workflow | FAILURE | <repr or string>"
    """
    logger = logging.getLogger("echolon.backtest")
    if isinstance(error, BaseException):
        logger.critical(
            f"[{context.upper()}] {workflow} | FAILURE | {type(error).__name__}: {error}",
            exc_info=(type(error), error, error.__traceback__),
        )
    else:
        logger.critical(f"[{context.upper()}] {workflow} | FAILURE | {error}")
```

- [ ] **Step 4: Run both new tests**

Run: `pytest tests/backtest/test_logging_utils.py -v`

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add echolon/backtest/logging_utils.py tests/backtest/test_logging_utils.py
git commit -m "feat(logging): log_workflow_failure accepts Exception; records traceback"
```

---

## Task P0.3 — ContextVar for run_context (parallel-safe)

**Files:**
- Modify: `echolon/backtest/logging_utils.py`
- Modify: `tests/backtest/test_logging_utils.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/backtest/test_logging_utils.py`:

```python
import asyncio


def test_run_context_isolated_across_asyncio_tasks():
    """Parallel trials (asyncio or concurrent.futures) must not share run_context."""
    async def setter_a():
        logging_utils.set_run_context("optimization")
        await asyncio.sleep(0.01)
        assert logging_utils.get_run_context() == "optimization"

    async def setter_b():
        logging_utils.set_run_context("debug")
        await asyncio.sleep(0.01)
        assert logging_utils.get_run_context() == "debug"

    async def runner():
        await asyncio.gather(setter_a(), setter_b())

    asyncio.run(runner())
```

- [ ] **Step 2: Run to verify the test is plausible (may flake with current module-global)**

Run: `pytest tests/backtest/test_logging_utils.py::test_run_context_isolated_across_asyncio_tasks -v`

Expected: FAIL (or PASS-by-luck if the gather races don't interleave). The fix below makes it deterministic.

- [ ] **Step 3: Convert module global to ContextVar**

In `echolon/backtest/logging_utils.py`, replace:

```python
# Module-level context for components to check
_current_context: RunContext = "debug"


def set_run_context(context: RunContext) -> None:
    global _current_context
    _current_context = context


def get_run_context() -> RunContext:
    return _current_context
```

with:

```python
from contextvars import ContextVar

_current_context: ContextVar[RunContext] = ContextVar("echolon_run_context", default="debug")


def set_run_context(context: RunContext) -> None:
    """Set the run context for the current async/thread context.

    ContextVar semantics: asyncio tasks and concurrent.futures workers each
    get an isolated copy, so parallel Optuna trials do not race.
    """
    _current_context.set(context)


def get_run_context() -> RunContext:
    """Read the run context for the current async/thread context."""
    return _current_context.get()
```

- [ ] **Step 4: Run the test**

Run: `pytest tests/backtest/test_logging_utils.py::test_run_context_isolated_across_asyncio_tasks -v`

Expected: PASS deterministically.

- [ ] **Step 5: Commit**

```bash
git add echolon/backtest/logging_utils.py tests/backtest/test_logging_utils.py
git commit -m "fix(logging): ContextVar for run_context; parallel-safe across tasks"
```

---

## Task P0.4 — Drop stale `modules.quant_engine.*` logger-name lists

**Files:**
- Modify: `echolon/backtest/logging_utils.py`

The `setup_backtest_logging("optimization")` branch (lines ~79–101) enumerates logger names like `modules.quant_engine.backtest.engine.backtrader_strategy` that do not exist post-reorg. The correct names are `echolon.backtest.engine.backtrader_strategy`, etc.

- [ ] **Step 1: Enumerate current library loggers**

```bash
cd /home/yzj/projects/quantitive_trading/echolon
rg -l '^logger\s*=\s*logging\.getLogger\(__name__\)' echolon/backtest echolon/indicators echolon/data | sort -u
```

Produces the list of modules that actually exist. Expected to include:

```
echolon/backtest/engine/backtrader_strategy.py
echolon/backtest/engine/backtest_runner.py
echolon/backtest/engine/backtrader_engine.py
echolon/backtest/engine/hooks/contract_aware/broker.py
echolon/backtest/engine/hooks/contract_aware/hook.py
echolon/backtest/engine/hooks/session_aware/hook.py
echolon/backtest/mfe_mae.py
echolon/backtest/optimization/optuna_study.py
echolon/backtest/wfa/runner.py
echolon/indicators/engine/processor.py
echolon/indicators/optimization/interday_regime_optimizer.py
```

- [ ] **Step 2: Replace the stale list in `setup_backtest_logging`**

In `echolon/backtest/logging_utils.py`, replace the `optimization`-branch logger-name list with the real names:

```python
    if run_context == "optimization":
        root_logger = logging.getLogger()
        root_logger.setLevel(logging.WARNING)

        # Quiet high-volume bar-level / trial-level loggers (ERROR+).
        # These are the modules that log inside tight loops.
        for logger_name in [
            "echolon.backtest",
            "echolon.backtest.engine",
            "echolon.backtest.engine.backtrader_strategy",
            "echolon.backtest.engine.backtrader_engine",
            "echolon.backtest.engine.backtest_runner",
            "echolon.backtest.engine.hooks.contract_aware.broker",
            "echolon.backtest.engine.hooks.contract_aware.hook",
            "echolon.backtest.engine.hooks.session_aware.hook",
            "echolon.backtest.mfe_mae",
            "echolon.backtest.optimization.optuna_study",
            "echolon.backtest.wfa.runner",
            "echolon.indicators.engine.processor",
            "echolon.indicators.optimization.interday_regime_optimizer",
        ]:
            logging.getLogger(logger_name).setLevel(logging.ERROR)

        # Suppress backtrader's internal logging
        logging.getLogger("backtrader").setLevel(logging.ERROR)
        logging.getLogger("backtrader.broker").setLevel(logging.ERROR)
        logging.getLogger("backtrader.cerebro").setLevel(logging.ERROR)
        logging.getLogger("matplotlib").setLevel(logging.ERROR)
```

Replace the `debug` branch similarly:

```python
    elif run_context == "debug":
        root_logger = logging.getLogger()
        root_logger.setLevel(logging.INFO)  # NOT DEBUG — per-module opt-in via ECHOLON_DEBUG_MODULES (Phase 3)

        for logger_name in [
            "echolon.backtest",
            "echolon.backtest.engine.backtrader_strategy",
            "echolon.indicators.engine.processor",
        ]:
            logging.getLogger(logger_name).setLevel(logging.INFO)

        logging.getLogger("matplotlib").setLevel(logging.WARNING)
```

And `best_trial`:

```python
    elif run_context == "best_trial":
        root_logger = logging.getLogger()
        root_logger.setLevel(logging.INFO)

        logging.getLogger("echolon.backtest").setLevel(logging.INFO)
        logging.getLogger("echolon.backtest.engine.backtrader_strategy").setLevel(logging.INFO)

        # Suppress noisy sub-components
        logging.getLogger("echolon.backtest.engine.hooks.contract_aware.broker").setLevel(logging.WARNING)
        logging.getLogger("matplotlib").setLevel(logging.ERROR)
```

- [ ] **Step 3: Write a regression test for logger-name validity**

Append to `tests/backtest/test_logging_utils.py`:

```python
import importlib


def test_setup_backtest_logging_references_real_loggers():
    """setup_backtest_logging must not reference logger names that
    correspond to non-existent modules (regression: previously referenced
    `modules.quant_engine.*` which didn't exist post-reorg)."""
    import ast
    from pathlib import Path

    src_path = Path(importlib.import_module("echolon.backtest.logging_utils").__file__)
    tree = ast.parse(src_path.read_text())

    # Collect every string literal inside setup_backtest_logging that looks
    # like a dotted logger name starting with echolon.
    logger_names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "setup_backtest_logging":
            for sub in ast.walk(node):
                if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                    if sub.value.startswith("echolon."):
                        logger_names.append(sub.value)

    assert logger_names, "expected echolon.* logger names inside setup_backtest_logging"

    # Each must correspond to an importable module.
    for name in logger_names:
        try:
            importlib.import_module(name)
        except ImportError as exc:
            raise AssertionError(
                f"Logger name {name!r} referenced in setup_backtest_logging "
                f"does not resolve to an importable module: {exc}"
            )
```

- [ ] **Step 4: Run**

Run: `pytest tests/backtest/test_logging_utils.py::test_setup_backtest_logging_references_real_loggers -v`

Expected: PASS.

- [ ] **Step 5: Run full suite**

Run: `pytest -q`

Expected: green.

- [ ] **Step 6: Commit**

```bash
git add echolon/backtest/logging_utils.py tests/backtest/test_logging_utils.py
git commit -m "fix(logging): update setup_backtest_logging to real post-reorg logger names"
```

---

## Task P0.5 — Phase 0 marker commit

- [ ] **Step 1: Mark phase complete**

```bash
git commit --allow-empty -m "chore: phase 0 (logging_utils hygiene) complete"
```

Phase 0 is shippable standalone.

---

# PHASE 1 — Fill the error catalog + wire the top 40 bare raises

**Rationale:** `echolon/errors.py` defines 13 catalog codes. None are raised anywhere in the library outside `native/validation/*` and `config/markets/*`. 139 bare `raise` sites bypass the catalog. Phase 1 adds the missing codes, then converts the 40 highest-value bare raises (prioritized by LLM-debug value: strategy authoring errors first, then data-loading, then optimization).

Phase 1 has 7 tasks:
- P1.1: Add missing catalog codes (no behavior change)
- P1.2: Strategy layer conversions (STR-*, VAL-*, PRM-*)
- P1.3: Data layer conversions (DAT-*)
- P1.4: Indicators layer conversions (IND-*)
- P1.5: Backtest layer conversions (new BT-*)
- P1.6: Live layer conversions (new LIV-*)
- P1.7: AST regression test forbidding bare `raise` in converted subsystems

## Task P1.1 — Add missing catalog codes

**Files:**
- Modify: `echolon/errors.py`
- Test: `tests/native/test_errors.py` (existing, extend)

- [ ] **Step 1: Write the failing test**

Append to `tests/native/test_errors.py` (create if needed):

```python
import pytest

from echolon.errors import ERROR_CATALOG, raise_error, DataError, IndicatorError

# New codes added in Phase 1
NEW_CODES = [
    "DAT-002",  # corrupt state file
    "DAT-003",  # missing contract data file
    "DAT-004",  # empty / degenerate calendar
    "IND-003",  # all-NaN indicator column
    "IND-004",  # degenerate optimizer result
    "BT-001",   # strategy on_bar exception
    "BT-002",   # zero-trades failure
    "BT-003",   # Optuna trial constraint violation
    "LIV-001",  # broker disconnect / unavailable
    "LIV-002",  # order rejected by broker
    "LIV-003",  # QMT callback error
]


@pytest.mark.parametrize("code", NEW_CODES)
def test_new_catalog_code_exists(code):
    assert code in ERROR_CATALOG, f"{code} missing from ERROR_CATALOG"
    entry = ERROR_CATALOG[code]
    assert "class" in entry
    assert "what" in entry and entry["what"], f"{code}: what must be a non-empty string"
    assert "why" in entry and entry["why"], f"{code}: why must be non-empty"
    assert "fix_template" in entry and entry["fix_template"], f"{code}: fix_template must be non-empty"


@pytest.mark.parametrize("code", NEW_CODES)
def test_new_catalog_code_raises(code):
    with pytest.raises(Exception) as exc:
        raise_error(code)
    assert exc.value.code == code
```

- [ ] **Step 2: Run tests to verify failure**

Run: `pytest tests/native/test_errors.py -v -k "new_catalog"`

Expected: 22 failures (11 codes × 2 tests) — `AssertionError: DAT-002 missing from ERROR_CATALOG`.

- [ ] **Step 3: Add the codes**

Edit `echolon/errors.py`. Append to `ERROR_CATALOG` dict (before the closing brace):

```python
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
```

Note that `BT-001`, `BT-002`, `BT-003`, `LIV-001`, `LIV-002`, `LIV-003` attach to the `EchelonError` base class because there is no `BacktestError` or `LiveError` subclass yet. Keep it that way — subclasses are optional grouping and can be added later without breaking `raise_error(code=...)`.

- [ ] **Step 4: Run tests**

Run: `pytest tests/native/test_errors.py -v -k "new_catalog"`

Expected: 22 passed.

- [ ] **Step 5: Run full suite**

Run: `pytest -q`

Expected: green.

- [ ] **Step 6: Commit**

```bash
git add echolon/errors.py tests/native/test_errors.py
git commit -m "feat(errors): add DAT-002..004, IND-003/004, BT-001..003, LIV-001..003"
```

---

## Task P1.2 — Strategy layer conversions (STR/VAL/PRM)

**Files:**
- Modify: `echolon/strategy/loader.py`, `echolon/strategy/parameter_architecture.py`, `echolon/strategy/component.py`
- Test: `tests/strategy/test_error_codes.py` (new)

This task wires the catalog into the five most common strategy-author failure modes. Phase 4 will extend it with pre-flight validation; here we only convert existing bare raises.

- [ ] **Step 1: Create the directory + the first failing test**

```bash
mkdir -p /home/yzj/projects/quantitive_trading/echolon/tests/strategy
```

Create `tests/strategy/test_error_codes.py`:

```python
"""Strategy-layer errors must use catalog codes, not bare Python exceptions."""
from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest

from echolon.errors import EchelonError, StrategyStructureError


def test_loader_missing_file_raises_str_001(tmp_path: Path):
    """Loader should raise STR-001 when a required strategy file is missing."""
    # Create a 6-file directory (missing one of the 7 required)
    for name in ("entry.py", "exit.py", "risk.py", "sizer.py", "component.py", "strategy_params.py"):
        (tmp_path / name).write_text("# stub")
    # intentionally skip "strategy_indicator_list.json"

    from echolon.strategy.loader import load_strategy_from_dir

    with pytest.raises(StrategyStructureError) as exc:
        load_strategy_from_dir(tmp_path)

    assert exc.value.code == "STR-001"
    assert "strategy_indicator_list.json" in str(exc.value)


def test_loader_missing_class_raises_str_002(tmp_path: Path):
    """Loader should raise STR-002 when a required class name is not exported."""
    # Full 7-file tree but entry.py's class is named wrong
    for name in ("exit.py", "risk.py", "sizer.py", "component.py", "strategy_params.py"):
        (tmp_path / name).write_text("# stub")
    (tmp_path / "strategy_indicator_list.json").write_text("{}")
    (tmp_path / "entry.py").write_text(dedent("""
        class NotEntry:
            pass
    """))

    from echolon.strategy.loader import load_strategy_from_dir

    with pytest.raises(StrategyStructureError) as exc:
        load_strategy_from_dir(tmp_path)

    assert exc.value.code == "STR-002"
    assert "Entry" in str(exc.value)


def test_component_not_implemented_raises_str_003():
    """A component subclass without the required method must raise STR-003."""
    from echolon.strategy.component import EntryComponent

    class BadEntry(EntryComponent):
        pass  # does not implement evaluate()

    bad = BadEntry.__new__(BadEntry)  # skip __init__ for unit test
    with pytest.raises(EchelonError) as exc:
        bad.evaluate(bar=None)

    assert exc.value.code == "STR-003"
    assert "evaluate" in str(exc.value)


def test_parameter_missing_printlog_raises_prm_001():
    """Parameter framework should raise PRM-001 when 'printlog' is missing."""
    from echolon.strategy.parameter_architecture import validate_component_params

    with pytest.raises(EchelonError) as exc:
        validate_component_params(
            component_key="entry_params",
            params={"threshold": 50},  # missing 'printlog'
        )

    assert exc.value.code == "PRM-001"
    assert "printlog" in str(exc.value)
```

- [ ] **Step 2: Run to confirm the tests fail for the right reason**

Run: `pytest tests/strategy/test_error_codes.py -v`

Expected: FAIL — likely `FileNotFoundError`, `AttributeError`, `NotImplementedError`, and a generic validation error instead of catalog codes.

- [ ] **Step 3: Wire `STR-001` in `strategy/loader.py`**

Read `echolon/strategy/loader.py` to locate the "required files" check (the audit reported it around line 74–75, raising `FileNotFoundError`). Replace the bare raise with:

```python
from echolon.errors import raise_error

REQUIRED_FILES = [
    "entry.py",
    "exit.py",
    "risk.py",
    "sizer.py",
    "component.py",
    "strategy_params.py",
    "strategy_indicator_list.json",
]


def load_strategy_from_dir(strategy_dir: Path):
    strategy_dir = Path(strategy_dir)
    missing = [f for f in REQUIRED_FILES if not (strategy_dir / f).exists()]
    if missing:
        raise_error(
            "STR-001",
            strategy_dir=str(strategy_dir),
            missing_files=", ".join(missing),
        )
    # ... existing load logic
```

(Adapt the exact integration point to the current file shape; the invariant is: the "missing file" check uses `raise_error("STR-001", ...)` with the `strategy_dir` and `missing_files` context.)

- [ ] **Step 4: Wire `STR-002` in `strategy/loader.py`**

Wherever the loader does `module.EntryComponent` or `getattr(module, "Entry")` and raises `AttributeError` on failure, replace with:

```python
try:
    cls = getattr(module, expected_class_name)
except AttributeError:
    found = [name for name in dir(module) if not name.startswith("_")]
    raise_error(
        "STR-002",
        file=str(module_path),
        expected_class=expected_class_name,
        found_classes=", ".join(found),
    )
```

- [ ] **Step 5: Wire `STR-003` in `strategy/component.py`**

For each abstract method in `EntryComponent`, `ExitComponent`, `RiskComponent`, `SizerComponent` that currently `raise NotImplementedError(...)`, replace:

```python
def evaluate(self, bar):
    raise_error(
        "STR-003",
        file=type(self).__module__,
        class_name=type(self).__name__,
        missing_method="evaluate",
    )
```

(Do this for every abstract method that today raises `NotImplementedError`; the audit mentioned lines 253, 265, 277, 292.)

- [ ] **Step 6: Wire `PRM-001` in `strategy/parameter_architecture.py`**

The audit reported `parameter_architecture.py:117–118` collects errors into a list. Extract a `validate_component_params(component_key, params)` helper that raises on the first violation:

```python
def validate_component_params(component_key: str, params: dict) -> None:
    """Raise PRM-001 if `printlog` is missing from a component-params dict."""
    if "printlog" not in params:
        raise_error(
            "PRM-001",
            file=__file__,  # caller can override via context
            function="validate_component_params",
            component_key=component_key,
        )
```

Callers of the old list-collecting validator either call this new helper, or (if they need to collect multiple errors) catch and re-aggregate.

- [ ] **Step 7: Run the tests**

Run: `pytest tests/strategy/test_error_codes.py -v`

Expected: 4 passed.

- [ ] **Step 8: Run the full suite**

Run: `pytest -q`

Expected: green (new tests pass; no existing tests relied on the bare exception types).

If an existing test DOES fail because it expected a bare `AttributeError`, update it to expect `StrategyStructureError` / check the `.code` attribute.

- [ ] **Step 9: Commit**

```bash
git add echolon/strategy/loader.py echolon/strategy/component.py \
        echolon/strategy/parameter_architecture.py tests/strategy/test_error_codes.py
git commit -m "feat(strategy): wire STR-001..003 and PRM-001 via raise_error"
```

---

## Task P1.3 — Data layer conversions

**Files:**
- Modify: `echolon/data/loaders/session_availability_loader.py`, `echolon/data/loaders/contract_loader.py`, `echolon/data/transformers/calendar_generator.py`, `echolon/live/trading_slot.py`
- Test: `tests/data/test_error_codes.py` (new)

This task converts the three most impactful silent-fallback sites in the data layer to use `DAT-002`, `DAT-003`, `DAT-004` catalog codes.

- [ ] **Step 1: Write the failing tests**

Create `tests/data/test_error_codes.py`:

```python
"""Data-layer errors should use catalog codes where appropriate."""
import json
from pathlib import Path

import pytest

from echolon.errors import DataError


def test_corrupt_state_raises_dat_002(tmp_path: Path):
    """live.trading_slot._load_state_file must raise DAT-002 on corrupt JSON,
    not silently return {}."""
    state_file = tmp_path / "strategy_state.json"
    state_file.write_text("{ this is not valid json")

    from echolon.live.trading_slot import _load_state_file

    with pytest.raises(DataError) as exc:
        _load_state_file(str(state_file))

    assert exc.value.code == "DAT-002"
    assert "strategy_state.json" in str(exc.value)


def test_missing_main_contract_raises_dat_003(tmp_path: Path):
    """contract_rules._load_main_contract_data raises DAT-003 with a fix path."""
    from echolon.markets.shfe.contract_rules import _load_main_contract_data

    with pytest.raises(DataError) as exc:
        _load_main_contract_data("al", raw_data_dir=tmp_path)

    assert exc.value.code == "DAT-003"
    assert "al" in str(exc.value)


def test_empty_calendar_generation_raises_dat_004(tmp_path: Path):
    """CalendarGenerator.generate raises DAT-004 when zero valid dates remain."""
    import pandas as pd
    from echolon.data.transformers.calendar_generator import CalendarGenerator

    gen = CalendarGenerator(output_dir=str(tmp_path))
    empty_df = pd.DataFrame(columns=["date", "open", "close"])

    with pytest.raises(DataError) as exc:
        gen.generate(df=empty_df, start_date="2024-01-01", end_date="2024-12-31")

    assert exc.value.code == "DAT-004"
```

- [ ] **Step 2: Run tests, confirm failure**

Run: `pytest tests/data/test_error_codes.py -v`

Expected: 3 failures (current behavior is silent `{}` / `FileNotFoundError` / empty DataFrame).

- [ ] **Step 3: Wire DAT-002 in `live/trading_slot.py`**

Replace the current silent `_load_state_file` (per the audit, lines 395–400 return `{}` on any error):

```python
from echolon.errors import raise_error


def _load_state_file(path: str) -> dict:
    """Load strategy_state.json. Raises DAT-002 if the file exists but is corrupt.
    Returns {} only when the file does NOT exist (cold start is a valid state)."""
    import json
    import os

    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r") as f:
            return json.load(f)
    except json.JSONDecodeError as exc:
        raise_error("DAT-002", path=path, error=str(exc))
```

- [ ] **Step 4: Wire DAT-003 in `markets/shfe/contract_rules.py`**

Find the `FileNotFoundError` raise in `_load_main_contract_data` and replace with:

```python
if not csv_path.exists():
    raise_error(
        "DAT-003",
        path=str(csv_path),
        symbol=symbol,
    )
```

- [ ] **Step 5: Wire DAT-004 in `data/transformers/calendar_generator.py`**

Add a zero-row guard at the end of `generate()` (where the current behavior returns an empty DataFrame):

```python
if result.empty:
    raise_error(
        "DAT-004",
        market=self.market,
        instrument=self.instrument,
        start_date=str(start_date),
        end_date=str(end_date),
        rows_seen=len(df),
    )
return result
```

- [ ] **Step 6: Run the new tests**

Run: `pytest tests/data/test_error_codes.py -v`

Expected: 3 passed.

- [ ] **Step 7: Run tests/data**

Run: `pytest tests/data/ -q`

Expected: green. (Existing tests for these modules did not rely on the `{}` / empty-DF behavior, per the audit.)

- [ ] **Step 8: Commit**

```bash
git add echolon/live/trading_slot.py echolon/markets/shfe/contract_rules.py \
        echolon/data/transformers/calendar_generator.py tests/data/test_error_codes.py
git commit -m "feat(data): wire DAT-002..004 at the three load-bearing silent-fallback sites"
```

---

## Task P1.4 — Indicators layer conversions

**Files:**
- Modify: `echolon/indicators/engine/processor.py`, `echolon/indicators/optimization/interday_regime_optimizer.py`
- Test: `tests/indicators/test_error_codes.py` (new)

This task wires `IND-001` (indicator name casing mismatch), `IND-002` (undeclared indicator in JSON), and `IND-003` (all-NaN column) — the latter gets a metadata warning file instead of an exception. `IND-004` (degenerate optimizer) is Phase 2's territory.

- [ ] **Step 1: Write the failing tests**

Create `tests/indicators/test_error_codes.py`:

```python
"""Indicator-layer errors should use catalog codes; all-NaN writes warn to sidecar."""
import json
from pathlib import Path

import pandas as pd
import pytest

from echolon.errors import IndicatorError


def test_unknown_indicator_name_raises_ind_002():
    """processor raises IND-002 when user code references an indicator not in the mapping."""
    from echolon.indicators.engine.processor import IndicatorProcessor

    # Minimal invocation that triggers name-resolution without requiring full setup
    with pytest.raises(IndicatorError) as exc:
        IndicatorProcessor._resolve_function(None, indicator_name="definitely_not_real")

    assert exc.value.code == "IND-002"
    assert "definitely_not_real" in str(exc.value)


def test_all_nan_column_writes_sidecar_warning(tmp_path: Path):
    """When >80% of an indicator column is NaN, processor writes a .warnings.json sidecar."""
    from echolon.indicators.engine.processor import _write_nan_warnings_sidecar

    # Simulate an output DataFrame with one mostly-NaN column
    df = pd.DataFrame({
        "date": pd.date_range("2024-01-01", periods=10),
        "rsi_14": [float("nan")] * 9 + [50.0],
        "macd": list(range(10)),
    })

    sidecar_path = tmp_path / "out.warnings.json"
    _write_nan_warnings_sidecar(
        df=df,
        output_path=tmp_path / "out.csv",
        nan_threshold=0.8,
    )

    assert sidecar_path.exists()
    payload = json.loads(sidecar_path.read_text())
    assert "rsi_14" in payload["warnings"]
    assert payload["warnings"]["rsi_14"]["code"] == "IND-003"
    assert "macd" not in payload["warnings"]  # well-populated column is not flagged
```

- [ ] **Step 2: Run to confirm failure**

Run: `pytest tests/indicators/test_error_codes.py -v`

Expected: FAIL — `_resolve_function` and `_write_nan_warnings_sidecar` don't exist yet.

- [ ] **Step 3: Wire IND-002 at the indicator-name-resolution site**

In `echolon/indicators/engine/processor.py`, locate the site (around line 777 per the audit) where a missing function mapping currently does `logger.warning(...); continue`. Replace with:

```python
@staticmethod
def _resolve_function(processor: "IndicatorProcessor | None", indicator_name: str):
    # Existing mapping-lookup logic
    function = FUNCTION_MAP.get(indicator_name)
    if function is None:
        raise_error(
            "IND-002",
            indicator=indicator_name,
            file=__file__,
            line="<indicator dispatch>",
        )
    return function
```

Update the caller (the loop around line 777) to call `_resolve_function(self, name)` and propagate the exception instead of `continue`-ing.

- [ ] **Step 4: Add the sidecar-warning helper**

Add to `echolon/indicators/engine/processor.py`:

```python
import json
import os


def _write_nan_warnings_sidecar(
    df: pd.DataFrame,
    output_path: Path | str,
    nan_threshold: float = 0.8,
) -> None:
    """Inspect df for columns whose NaN ratio exceeds threshold and write
    <output_path>.warnings.json with a per-column IND-003 payload.

    The sidecar file is present iff at least one column was flagged.
    """
    output_path = Path(output_path)
    warnings = {}
    for col in df.columns:
        if col in ("date", "datetime", "contract"):
            continue
        total = len(df)
        nan_rows = int(df[col].isna().sum())
        if total == 0:
            continue
        ratio = nan_rows / total
        if ratio >= nan_threshold:
            warnings[col] = {
                "code": "IND-003",
                "indicator": col,
                "rows": total,
                "nan_rows": nan_rows,
                "nan_ratio": round(ratio, 4),
            }
    if warnings:
        sidecar = output_path.with_suffix(output_path.suffix + ".warnings.json")
        sidecar.write_text(json.dumps({"warnings": warnings}, indent=2))
```

- [ ] **Step 5: Call the helper from the CSV write path**

In the processor's main flow (the `output_df.to_csv(output_file, index=False)` site around line 252 per the audit), append:

```python
output_df.to_csv(output_file, index=False)
_write_nan_warnings_sidecar(output_df, output_file)
```

- [ ] **Step 6: Run tests**

Run: `pytest tests/indicators/test_error_codes.py -v`

Expected: 2 passed.

- [ ] **Step 7: Run the indicators suite**

Run: `pytest tests/indicators/ -q`

Expected: green.

- [ ] **Step 8: Commit**

```bash
git add echolon/indicators/engine/processor.py tests/indicators/test_error_codes.py
git commit -m "feat(indicators): IND-002 on missing mapping, IND-003 sidecar for all-NaN columns"
```

---

## Task P1.5 — Backtest layer conversions

**Files:**
- Modify: `echolon/backtest/engine/backtrader_strategy.py`, `echolon/backtest/optimization/optuna_study.py`, `echolon/backtest/engine/backtest_runner.py`
- Test: `tests/backtest/test_error_codes.py` (new)

- [ ] **Step 1: Write the failing tests**

Create `tests/backtest/test_error_codes.py`:

```python
"""Backtest-layer errors use BT-001/002/003 catalog codes."""
import pytest

from echolon.errors import EchelonError


def test_strategy_on_bar_exception_wraps_with_bt_001():
    """A strategy.on_bar() exception must be re-raised as BT-001 with bar context."""
    from echolon.backtest.engine.backtrader_strategy import _wrap_on_bar_exception

    inner = KeyError("entry_rule")
    with pytest.raises(EchelonError) as exc:
        _wrap_on_bar_exception(
            exc=inner,
            bar_index=42,
            trading_date="2024-03-15",
            contract="al2403",
            position_size=0,
            file="entry.py",
        )

    assert exc.value.code == "BT-001"
    assert "al2403" in str(exc.value)
    assert "42" in str(exc.value)


def test_zero_trades_after_backtest_raises_bt_002():
    """run_backtest wraps the zero-trades diagnostic in a BT-002 raise."""
    from echolon.backtest.engine.backtest_runner import _assert_trades_produced

    with pytest.raises(EchelonError) as exc:
        _assert_trades_produced(
            total_trades=0,
            bars_processed=1000,
            entry_signals_generated=0,
            entry_signals_blocked=0,
            risk_blocks=0,
        )

    assert exc.value.code == "BT-002"


def test_optuna_trial_constraint_violation_raises_bt_003():
    """The optimizer's constraint-check helper raises BT-003 with params."""
    from echolon.backtest.optimization.optuna_study import _raise_constraint_violation

    with pytest.raises(EchelonError) as exc:
        _raise_constraint_violation(
            trial_number=12,
            constraint="MIN_RETURN_SEPARATION",
            required=0.001,
            actual=-0.0005,
            params={"entry_rsi": 30, "exit_atr": 2.0},
        )

    assert exc.value.code == "BT-003"
```

- [ ] **Step 2: Run, confirm failure**

Run: `pytest tests/backtest/test_error_codes.py -v`

Expected: FAIL — helper functions don't exist yet.

- [ ] **Step 3: Add `_wrap_on_bar_exception` in `backtrader_strategy.py`**

Append to `echolon/backtest/engine/backtrader_strategy.py`:

```python
from echolon.errors import raise_error


def _wrap_on_bar_exception(
    exc: Exception,
    bar_index: int,
    trading_date,
    contract,
    position_size,
    file: str,
) -> None:
    raise_error(
        "BT-001",
        file=file,
        bar_index=bar_index,
        trading_date=str(trading_date),
        contract=str(contract),
        position_size=position_size,
        exception_repr=f"{type(exc).__name__}: {exc}",
    )
```

Find the current `strategy.on_bar()` call site in the strategy bridge — wrap it:

```python
try:
    self._strategy.on_bar(bar)
except Exception as exc:
    _wrap_on_bar_exception(
        exc=exc,
        bar_index=self._bar_index,
        trading_date=self._current_date,
        contract=self._current_contract,
        position_size=self.position.size if self.position else 0,
        file=type(self._strategy).__module__,
    )
```

- [ ] **Step 4: Add `_assert_trades_produced` in `backtest_runner.py`**

Append to `echolon/backtest/engine/backtest_runner.py`:

```python
from echolon.errors import raise_error
from echolon.backtest.logging_utils import log_zero_trades_warning, get_run_context


def _assert_trades_produced(
    total_trades: int,
    bars_processed: int,
    entry_signals_generated: int = 0,
    entry_signals_blocked: int = 0,
    risk_blocks: int = 0,
) -> None:
    """Raise BT-002 when a backtest completes with no trades. Logs the
    diagnostic hint first so the LLM reading logs sees both."""
    if total_trades > 0:
        return
    log_zero_trades_warning(
        context=get_run_context(),
        workflow="Backtest",
        bars_processed=bars_processed,
        entry_signals_generated=entry_signals_generated,
        entry_signals_blocked=entry_signals_blocked,
        risk_blocks=risk_blocks,
    )
    raise_error(
        "BT-002",
        bars_processed=bars_processed,
        entry_signals_generated=entry_signals_generated,
        entry_signals_blocked=entry_signals_blocked,
        risk_blocks=risk_blocks,
    )
```

Replace the current `if results.total_trades == 0: return` pattern at the end of `run_backtest` with a call to `_assert_trades_produced(...)`.

- [ ] **Step 5: Add `_raise_constraint_violation` in `optuna_study.py`**

Append:

```python
from echolon.errors import raise_error


def _raise_constraint_violation(
    trial_number: int,
    constraint: str,
    required,
    actual,
    params: dict,
) -> None:
    raise_error(
        "BT-003",
        trial_number=trial_number,
        constraint=constraint,
        required=required,
        actual=actual,
        params=params,
    )
```

Call it from the constraint-check branches that currently clamp score to 0.0 and silently return — at minimum, log the BT-003 via its exception (use `log_workflow_failure(..., error=exc)`), then suppress the raise so the trial still reports a score (Optuna catches exceptions and records NaN). The point is to emit the structured diagnostic even when the trial continues.

- [ ] **Step 6: Run tests**

Run: `pytest tests/backtest/test_error_codes.py -v`

Expected: 3 passed.

- [ ] **Step 7: Run full suite**

Run: `pytest -q`

Expected: green.

- [ ] **Step 8: Commit**

```bash
git add echolon/backtest/engine/backtrader_strategy.py \
        echolon/backtest/engine/backtest_runner.py \
        echolon/backtest/optimization/optuna_study.py \
        tests/backtest/test_error_codes.py
git commit -m "feat(backtest): BT-001 wrap on_bar exceptions, BT-002 zero-trades, BT-003 constraint"
```

---

## Task P1.6 — Live layer conversions

**Files:**
- Modify: `echolon/live/platforms/miniqmt/qmt_client.py`, `echolon/live/trading_slot.py`, `echolon/live/slot_aware_portfolio.py`
- Test: `tests/live/test_error_codes.py` (new)

- [ ] **Step 1: Write the failing tests**

Create `tests/live/test_error_codes.py`:

```python
"""Live-layer errors use LIV-001/002/003 catalog codes."""
import pytest

from echolon.errors import EchelonError


def test_broker_disconnect_raises_liv_001():
    from echolon.live.platforms.miniqmt.qmt_client import _raise_broker_unavailable

    with pytest.raises(EchelonError) as exc:
        _raise_broker_unavailable(
            account_id="test-acct-123",
            error="connection refused",
        )
    assert exc.value.code == "LIV-001"
    assert "test-acct-123" in str(exc.value)


def test_order_rejection_raises_liv_002():
    from echolon.live.platforms.miniqmt.qmt_client import _raise_order_rejected

    with pytest.raises(EchelonError) as exc:
        _raise_order_rejected(
            contract="al2404",
            direction="BUY",
            price=20000.0,
            size=5,
            broker_status=57,
            broker_message="price outside day range",
        )
    assert exc.value.code == "LIV-002"


def test_qmt_callback_error_raises_liv_003():
    from echolon.live.platforms.miniqmt.qmt_client import _raise_qmt_callback_error

    with pytest.raises(EchelonError) as exc:
        _raise_qmt_callback_error(
            seq_id=1234,
            qmt_status=57,
            raw={"foo": "bar"},
        )
    assert exc.value.code == "LIV-003"
```

- [ ] **Step 2: Run, confirm failure**

Run: `pytest tests/live/test_error_codes.py -v`

Expected: FAIL.

- [ ] **Step 3: Add helpers to `qmt_client.py`**

Append to `echolon/live/platforms/miniqmt/qmt_client.py`:

```python
from echolon.errors import raise_error


_QMT_STATUS_TO_ECHO = {
    48: "UNREPORTED",
    49: "WAIT_REPORTING",
    50: "SUBMITTED",
    53: "PARTIAL_CANCELED",
    54: "CANCELED",
    55: "PARTIAL_FILLED",
    56: "FILLED",
    57: "REJECTED",
}


def _raise_broker_unavailable(account_id: str, error: str) -> None:
    raise_error("LIV-001", platform="miniqmt", account_id=account_id, error=error)


def _raise_order_rejected(
    contract: str,
    direction: str,
    price: float,
    size: int,
    broker_status: int,
    broker_message: str,
) -> None:
    raise_error(
        "LIV-002",
        contract=contract,
        direction=direction,
        price=price,
        size=size,
        broker_status=broker_status,
        broker_message=broker_message,
    )


def _raise_qmt_callback_error(seq_id: int, qmt_status: int, raw) -> None:
    raise_error(
        "LIV-003",
        seq_id=seq_id,
        qmt_status=qmt_status,
        echo_status=_QMT_STATUS_TO_ECHO.get(qmt_status, f"UNKNOWN_{qmt_status}"),
        raw=str(raw),
    )
```

- [ ] **Step 4: Wire LIV-001 at the connect-failure site**

Replace the audit-mentioned bare `ConnectionError("Failed to connect to miniQMT")` (around line 375) with:

```python
_raise_broker_unavailable(account_id=self._account_id, error=str(exc))
```

- [ ] **Step 5: Wire LIV-002 where order rejections are observed**

In the order-response callback (wherever `xtconstant.STATUS_REJECTED` / status 57 is handled), call:

```python
_raise_order_rejected(
    contract=order.contract,
    direction=order.direction,
    price=order.price,
    size=order.size,
    broker_status=response.status,
    broker_message=response.message or "",
)
```

(This converts the silent order rejection that the audit flagged — `live_slot_aware_portfolio.py:185–186` and friends — into a loud, structured raise.)

- [ ] **Step 6: Wire LIV-003 at the QMT callback boundary**

Any `on_order_stock_async_response` / `on_trade_callback` handler that currently logs a bare dict should, on failure statuses, raise via `_raise_qmt_callback_error(...)`.

- [ ] **Step 7: Run tests**

Run: `pytest tests/live/test_error_codes.py -v`

Expected: 3 passed.

- [ ] **Step 8: Run full suite**

Run: `pytest -q`

Expected: green.

- [ ] **Step 9: Commit**

```bash
git add echolon/live/platforms/miniqmt/qmt_client.py tests/live/test_error_codes.py
git commit -m "feat(live): LIV-001/002/003 for broker disconnect, order rejection, QMT callback"
```

---

## Task P1.7 — AST regression: forbid bare raises in migrated subsystems

**Files:**
- Create: `tests/test_error_catalog_compliance.py`

- [ ] **Step 1: Write the regression test**

Create `tests/test_error_catalog_compliance.py`:

```python
"""Regression: in migrated subsystems, bare raise of generic exceptions is
forbidden at the module level. Tests only the subtrees listed in
MIGRATED_SUBSYSTEMS; add to that list as new subsystems are converted."""
import ast
import pathlib

MIGRATED_SUBSYSTEMS = [
    "strategy/loader.py",
    "strategy/parameter_architecture.py",
    "strategy/component.py",
    "data/loaders/session_availability_loader.py",
    "markets/shfe/contract_rules.py",
    "data/transformers/calendar_generator.py",
    "indicators/engine/processor.py",
    "backtest/engine/backtrader_strategy.py",
    "backtest/engine/backtest_runner.py",
    "backtest/optimization/optuna_study.py",
    "live/trading_slot.py",
    "live/platforms/miniqmt/qmt_client.py",
]

# Bare raises of these concrete types are what we forbid.
FORBIDDEN = {"ValueError", "RuntimeError", "TypeError", "FileNotFoundError", "AttributeError", "NotImplementedError"}


def _raise_node_is_forbidden(node: ast.Raise) -> bool:
    """Return True if the raise is a bare `raise Forbidden(...)` at any scope."""
    if node.exc is None:  # bare `raise`, re-raising — allowed
        return False
    call = node.exc
    if isinstance(call, ast.Call) and isinstance(call.func, ast.Name):
        return call.func.id in FORBIDDEN
    if isinstance(call, ast.Name):
        return call.id in FORBIDDEN
    return False


def test_migrated_subsystems_use_catalog():
    base = pathlib.Path(__file__).parent.parent / "echolon"
    offenders: list[tuple[str, int]] = []
    for rel in MIGRATED_SUBSYSTEMS:
        path = base / rel
        if not path.exists():
            continue
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Raise) and _raise_node_is_forbidden(node):
                offenders.append((rel, node.lineno))
    assert not offenders, (
        f"Migrated subsystems must use raise_error(code, ...); found bare raises at {offenders}"
    )
```

- [ ] **Step 2: Run**

Run: `pytest tests/test_error_catalog_compliance.py -v`

Expected: PASS — all migrations in P1.2–P1.6 leave no bare forbidden raises in the listed files. If it fails, the failure points list is the punch-list to finish.

- [ ] **Step 3: Commit**

```bash
git add tests/test_error_catalog_compliance.py
git commit -m "test: AST regression forbids bare raises in migrated subsystems"
```

---

## Task P1.8 — Phase 1 marker commit

```bash
git commit --allow-empty -m "chore: phase 1 (error catalog wiring) complete"
```

---

# PHASE 2 — Eliminate top-3 silent fallbacks

**Rationale:** Three silent-fallback patterns are load-bearing for the whole library's trust model:
1. `data/loaders/session_availability_loader._load` logs a warning + returns `None` (downstream `AttributeError`).
2. `indicators/engine/processor` writes all-NaN columns without flagging — Phase 1 added the sidecar but strategies still silently read the NaNs. Phase 2 adds a loader-side preflight.
3. `indicators/optimization/interday_regime_optimizer` returns degenerate best-trial (Phase 1 added BT-003 for per-trial; this adds IND-004 for the optimizer-final case).

## Task P2.1 — Session availability loader: fail loud

**Files:**
- Modify: `echolon/data/loaders/session_availability_loader.py`
- Test: `tests/data/test_session_availability_loader_fails_loudly.py` (new)

- [ ] **Step 1: Write the failing test**

Create `tests/data/test_session_availability_loader_fails_loudly.py`:

```python
"""When a caller did not pass `path=` or `market_data_dir=` AND the conventional
file does not exist, SessionAvailabilityLoader must raise DAT-003, not silently
default to empty data."""
import pytest

from echolon.errors import DataError


def test_loader_raises_when_conventional_file_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("ECHOLON_PROJECT_ROOT", str(tmp_path))
    from echolon.data.loaders.session_availability_loader import SessionAvailabilityLoader

    with pytest.raises(DataError) as exc:
        SessionAvailabilityLoader(
            market="SHFE",
            instrument="aluminum",
            bar_size_minutes=15,
        )
    assert exc.value.code in ("DAT-003",)


def test_loader_with_explicit_path_override_still_works(tmp_path):
    """If caller passes an explicit path, we don't auto-raise — the caller
    knows what they're doing."""
    # This test passes an explicit (non-existent) path. Loader currently
    # warns + returns empty. Keep that behavior for explicit overrides.
    from echolon.data.loaders.session_availability_loader import SessionAvailabilityLoader

    loader = SessionAvailabilityLoader(
        market="SHFE",
        instrument="aluminum",
        bar_size_minutes=15,
        path=str(tmp_path / "explicit_missing.csv"),
    )
    # No raise — empty data is valid when explicitly overridden
    assert loader._data == {}
```

- [ ] **Step 2: Run to confirm failure**

Run: `pytest tests/data/test_session_availability_loader_fails_loudly.py -v`

Expected: FAIL — current behavior is silent empty-data.

- [ ] **Step 3: Update `_load`**

In `echolon/data/loaders/session_availability_loader.py`, modify `_load` so that:
- If `self._path_override is not None` → existing warn-and-return-empty behavior (explicit override).
- If `self._path_override is None` and the conventional file is missing → `raise_error("DAT-003", path=str(file_path), symbol=self.instrument)`.

```python
def _load(self) -> None:
    from echolon.errors import raise_error

    if self._path_override is not None:
        file_path = Path(self._path_override)
        if not file_path.exists():
            logger.warning(
                f"[SESSION_AVAILABILITY] Explicit path_override points at missing file: {file_path}. "
                f"Bar counts will use defaults."
            )
            return
    else:
        market_data_dir = self._market_data_dir
        if market_data_dir is None:
            from echolon.config.paths_config import PathsConfig
            market_data_dir = PathsConfig.from_env().market_data_dir
        file_path = Path(market_data_dir) / self.market / self.instrument / "session_availability.csv"
        if not file_path.exists():
            raise_error("DAT-003", path=str(file_path), symbol=self.instrument)

    # ... existing CSV-reading logic below
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/data/test_session_availability_loader_fails_loudly.py -v`

Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add echolon/data/loaders/session_availability_loader.py tests/data/test_session_availability_loader_fails_loudly.py
git commit -m "feat(data): session_availability_loader raises DAT-003 on missing conventional file"
```

---

## Task P2.2 — Backtest loader checks NaN sidecar

**Files:**
- Modify: `echolon/data/loaders/backtest_data_loader.py`
- Test: `tests/data/test_backtest_loader_warns_on_nan_sidecar.py` (new)

- [ ] **Step 1: Write the failing test**

Create `tests/data/test_backtest_loader_warns_on_nan_sidecar.py`:

```python
"""If indicators CSV has a sibling .warnings.json sidecar (written by Phase 1's
IND-003 helper), the loader logs a WARNING naming the suspect columns."""
import json
from pathlib import Path

import pandas as pd


def test_loader_logs_warning_when_sidecar_present(tmp_path, caplog, monkeypatch):
    indicator_dir = tmp_path / "indicators"
    instrument = "aluminum"
    (indicator_dir / instrument).mkdir(parents=True)
    csv_path = indicator_dir / instrument / "strategy_indicators.csv"
    pd.DataFrame({"date": ["2024-01-01"], "rsi_14": [float("nan")]}).to_csv(csv_path, index=False)

    sidecar = csv_path.with_suffix(".csv.warnings.json")
    sidecar.write_text(json.dumps({
        "warnings": {
            "rsi_14": {"code": "IND-003", "indicator": "rsi_14", "rows": 1, "nan_rows": 1, "nan_ratio": 1.0}
        }
    }))

    from echolon.data.loaders.backtest_data_loader import load_backtest_data
    from echolon.config.markets.core.context import TradingContext

    ctx = TradingContext.__new__(TradingContext)
    ctx.market_code = "SHFE"
    ctx.instrument_name = instrument
    ctx.instrument_code = "al"

    # Provide a bogus market_data_dir so only the indicator sidecar path is exercised
    (tmp_path / "md" / "SHFE" / instrument).mkdir(parents=True)
    (tmp_path / "md" / "SHFE" / instrument / "trading_calendar.csv").write_text(
        "date,is_trading_day\n2024-01-01,1\n"
    )

    with caplog.at_level("WARNING", logger="echolon.data.loaders.backtest_data_loader"):
        try:
            load_backtest_data(
                ctx,
                indicator_dir=indicator_dir,
                market_data_dir=tmp_path / "md",
            )
        except Exception:
            # Loader may still raise on the ctx.encode_phase side; we only care
            # that the sidecar WARNING fired first.
            pass

    assert any("IND-003" in r.message for r in caplog.records)
    assert any("rsi_14" in r.message for r in caplog.records)
```

- [ ] **Step 2: Run to confirm failure**

Run: `pytest tests/data/test_backtest_loader_warns_on_nan_sidecar.py -v`

Expected: FAIL — loader ignores the sidecar.

- [ ] **Step 3: Add sidecar check to `load_backtest_data`**

In `echolon/data/loaders/backtest_data_loader.py`, after `indicators_data = pd.read_csv(indicators_path)` near line 101:

```python
# Check for IND-003 sidecar from the indicator writer
import json
sidecar = Path(indicators_path).with_suffix(Path(indicators_path).suffix + ".warnings.json")
if sidecar.exists():
    try:
        payload = json.loads(sidecar.read_text())
        warnings_block = payload.get("warnings", {})
        for col, info in warnings_block.items():
            logger.warning(
                f"[DATA_LOADER] {info.get('code', 'IND-003')}: indicator "
                f"'{col}' has {info.get('nan_ratio', 0):.1%} NaN "
                f"({info.get('nan_rows')}/{info.get('rows')} rows)"
            )
    except (json.JSONDecodeError, OSError):
        pass  # Sidecar is best-effort; don't let a corrupt sidecar break loading
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/data/test_backtest_loader_warns_on_nan_sidecar.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add echolon/data/loaders/backtest_data_loader.py tests/data/test_backtest_loader_warns_on_nan_sidecar.py
git commit -m "feat(data): loader warns on IND-003 sidecar from indicators writer"
```

---

## Task P2.3 — Regime optimizer: flag degenerate "best" result

**Files:**
- Modify: `echolon/indicators/optimization/interday_regime_optimizer.py`
- Test: `tests/indicators/test_regime_optimizer_degenerate.py` (new)

- [ ] **Step 1: Write the failing test**

Create `tests/indicators/test_regime_optimizer_degenerate.py`:

```python
"""When every Optuna trial fails a hard constraint, the optimizer must return
a result flagged with code IND-004 so the caller can refuse to deploy the params."""
import pytest


def test_degenerate_search_result_is_flagged(monkeypatch):
    from echolon.indicators.optimization.interday_regime_optimizer import (
        InterdayRegimeOptimizer,
        RegimeOptimizerConfig,
    )

    # Minimal: patch evaluate_regime_quality to always clamp to 0 (fail constraint)
    opt = InterdayRegimeOptimizer.__new__(InterdayRegimeOptimizer)
    opt.config = RegimeOptimizerConfig(n_trials=3)
    opt.study = None
    opt.best_params = None
    opt.optimization_history = []
    opt._degenerate_trials = []

    def fake_objective(trial):
        opt._degenerate_trials.append({
            "trial_number": trial.number,
            "constraint": "MIN_RETURN_SEPARATION",
        })
        return 0.0

    # Simulate the summary helper that Phase 2 adds
    from echolon.indicators.optimization.interday_regime_optimizer import (
        _build_summary_result,
    )
    summary = _build_summary_result(
        n_trials=3,
        degenerate_trials=opt._degenerate_trials,
        best_params={"fast_ma_period": 10},
    )
    assert summary["degenerate"] is True
    assert summary["code"] == "IND-004"
    assert summary["trials_rejected"] == 3
```

- [ ] **Step 2: Run, confirm failure**

Run: `pytest tests/indicators/test_regime_optimizer_degenerate.py -v`

Expected: FAIL — `_build_summary_result` doesn't exist.

- [ ] **Step 3: Add the summary helper**

Append to `echolon/indicators/optimization/interday_regime_optimizer.py`:

```python
def _build_summary_result(
    n_trials: int,
    degenerate_trials: list[dict],
    best_params: dict,
) -> dict:
    """Build the post-optimization summary dict. Marks the result as degenerate
    (code IND-004) when every trial was rejected by constraint checks."""
    is_degenerate = len(degenerate_trials) == n_trials and n_trials > 0
    summary = {
        "best_params": best_params,
        "n_trials": n_trials,
        "trials_rejected": len(degenerate_trials),
        "degenerate": is_degenerate,
    }
    if is_degenerate:
        summary["code"] = "IND-004"
        # Group rejected reasons for the context dict
        from collections import Counter
        reasons = Counter(t.get("constraint", "unknown") for t in degenerate_trials)
        summary["rejected_reasons"] = dict(reasons)
        logger.warning(
            "[REGIME_OPTIMIZER] IND-004: all %d trials rejected by constraints %s. "
            "Loosen constraints or extend the historical window.",
            n_trials, dict(reasons),
        )
    return summary
```

- [ ] **Step 4: Wire the helper into `optimize()`**

In `InterdayRegimeOptimizer.optimize`, after the Optuna loop, replace the current "return best_params" with:

```python
summary = _build_summary_result(
    n_trials=self.config.n_trials,
    degenerate_trials=self._degenerate_trials,
    best_params=study.best_params,
)
return summary["best_params"], study, summary
```

Update the public `optimize_regime_params` wrapper to unwrap `summary["best_params"]` for existing callers, but also expose `summary` via a second return or an attribute (pick the least invasive depending on current signature; the test only exercises `_build_summary_result` directly so callers can migrate lazily).

- [ ] **Step 5: Run tests**

Run: `pytest tests/indicators/test_regime_optimizer_degenerate.py -v`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add echolon/indicators/optimization/interday_regime_optimizer.py tests/indicators/test_regime_optimizer_degenerate.py
git commit -m "feat(indicators): IND-004 summary flag on degenerate regime search"
```

---

## Task P2.4 — Phase 2 marker commit

```bash
git commit --allow-empty -m "chore: phase 2 (silent-fallback elimination) complete"
```

---

# PHASE 3 — Structured logging + noise reduction

**Rationale:** Even with Phase 0–2, log streams remain noisy and unstructured. Phase 3 adds (a) an opt-in JSON-lines handler for LLM agents consuming event streams, (b) a per-module DEBUG gate so users can zoom into one component without flooding the rest, and (c) demotes the worst per-bar / per-trial INFO spam to DEBUG.

## Task P3.1 — Opt-in JSON-lines handler

**Files:**
- Create: `echolon/_internal/structured_logging.py`
- Test: `tests/_internal/test_structured_logging.py` (new)

- [ ] **Step 1: Write the failing test**

```bash
mkdir -p /home/yzj/projects/quantitive_trading/echolon/tests/_internal
```

Create `tests/_internal/test_structured_logging.py`:

```python
"""JSON-lines logging handler: activates via env var, emits structured events."""
import io
import json
import logging
import os

import pytest


def test_enable_json_logging_formats_records_as_jsonl(monkeypatch, capsys):
    monkeypatch.setenv("ECHOLON_LOG_JSON", "1")

    from echolon._internal import structured_logging
    buf = io.StringIO()
    handler = structured_logging._make_json_handler(stream=buf)
    logger = logging.getLogger("echolon.test.structured")
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

    logger.info("hello")
    logger.handlers.remove(handler)

    lines = [line for line in buf.getvalue().splitlines() if line]
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["level"] == "INFO"
    assert record["module"] == "echolon.test.structured"
    assert record["message"] == "hello"
    assert "ts" in record


def test_enable_json_logging_captures_echolon_error_fields(monkeypatch):
    from echolon._internal import structured_logging
    from echolon.errors import raise_error

    buf = io.StringIO()
    handler = structured_logging._make_json_handler(stream=buf)
    logger = logging.getLogger("echolon.test.structured.err")
    logger.addHandler(handler)
    logger.setLevel(logging.ERROR)

    try:
        raise_error("DAT-001", path="/nonexistent.csv")
    except Exception as exc:
        logger.error("failure", exc_info=True)

    logger.handlers.remove(handler)
    lines = [line for line in buf.getvalue().splitlines() if line]
    record = json.loads(lines[0])
    assert "exc_info" in record
    # The EchelonError's code should appear in the formatted traceback
    assert "DAT-001" in record["exc_info"]
```

- [ ] **Step 2: Create the module**

```bash
mkdir -p /home/yzj/projects/quantitive_trading/echolon/echolon/_internal
[ -f /home/yzj/projects/quantitive_trading/echolon/echolon/_internal/__init__.py ] || touch /home/yzj/projects/quantitive_trading/echolon/echolon/_internal/__init__.py
```

Create `echolon/_internal/structured_logging.py`:

```python
"""JSON-lines logging handler + per-module DEBUG gating.

Opt-in via env vars:
- ``ECHOLON_LOG_JSON=1``  emits JSON lines instead of free-form text.
- ``ECHOLON_DEBUG_MODULES=echolon.backtest.engine.hooks.*,echolon.indicators.*``
  enables DEBUG level on matched logger names (fnmatch-style patterns).

Call ``install_structured_logging()`` once at CLI/application startup to honour
the env vars; library modules never do this themselves.
"""
from __future__ import annotations

import fnmatch
import io
import json
import logging
import os
import sys
import traceback
from datetime import datetime, timezone
from typing import Optional, TextIO


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "module": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exc_info"] = "".join(traceback.format_exception(*record.exc_info)).strip()
        # Extra attrs set via logger.xxx(..., extra={"slot_id": "..."})
        for key, value in record.__dict__.items():
            if key in ("args", "msg", "message", "name", "levelname", "levelno",
                      "pathname", "filename", "module", "exc_info", "exc_text",
                      "stack_info", "lineno", "funcName", "created", "msecs",
                      "relativeCreated", "thread", "threadName", "processName",
                      "process"):
                continue
            try:
                json.dumps(value)
                payload[key] = value
            except (TypeError, ValueError):
                payload[key] = repr(value)
        return json.dumps(payload)


def _make_json_handler(stream: Optional[TextIO] = None) -> logging.Handler:
    handler = logging.StreamHandler(stream if stream is not None else sys.stderr)
    handler.setFormatter(_JsonFormatter())
    return handler


def _configure_module_debug(patterns: list[str]) -> None:
    """Enable DEBUG level on every existing logger whose name matches any pattern."""
    for name in list(logging.root.manager.loggerDict):
        for pat in patterns:
            if fnmatch.fnmatch(name, pat):
                logging.getLogger(name).setLevel(logging.DEBUG)
                break


def install_structured_logging() -> None:
    """Honour ECHOLON_LOG_JSON and ECHOLON_DEBUG_MODULES env vars.

    Idempotent: calling multiple times is safe (doesn't double-install handlers).
    """
    root = logging.getLogger()

    if os.getenv("ECHOLON_LOG_JSON", "").lower() in ("1", "true", "yes"):
        already_installed = any(
            isinstance(h.formatter, _JsonFormatter) for h in root.handlers
        )
        if not already_installed:
            # Remove existing handlers so output is purely JSON-lines
            for existing in list(root.handlers):
                root.removeHandler(existing)
            root.addHandler(_make_json_handler())

    modules_env = os.getenv("ECHOLON_DEBUG_MODULES", "").strip()
    if modules_env:
        patterns = [p.strip() for p in modules_env.split(",") if p.strip()]
        _configure_module_debug(patterns)
```

- [ ] **Step 3: Run tests**

Run: `pytest tests/_internal/test_structured_logging.py -v`

Expected: both pass.

- [ ] **Step 4: Commit**

```bash
git add echolon/_internal/structured_logging.py echolon/_internal/__init__.py \
        tests/_internal/__init__.py tests/_internal/test_structured_logging.py
git commit -m "feat(logging): opt-in JSON-lines handler and per-module DEBUG gate"
```

---

## Task P3.2 — Call `install_structured_logging` from CLI entry points

**Files:**
- Modify: `echolon/backtest/cli.py`, `echolon/native/cli/*.py` (whatever the CLI entry points are)
- Test: `tests/_internal/test_structured_logging.py` (extend)

- [ ] **Step 1: Find CLI entry points**

```bash
cd /home/yzj/projects/quantitive_trading/echolon
rg -l "^def main\(" echolon/ --type py
```

Typical entry points: `echolon/backtest/cli.py`, `echolon/native/cli/*.py`, `echolon/indicators/run.py` if CLI-invokable.

- [ ] **Step 2: Add the call at the top of each `main()`**

For each entry-point `main()` function, add:

```python
def main() -> None:
    from echolon._internal.structured_logging import install_structured_logging
    install_structured_logging()
    # ... existing body
```

- [ ] **Step 3: Write a smoke test**

Append to `tests/_internal/test_structured_logging.py`:

```python
def test_install_is_idempotent(monkeypatch):
    """Calling install_structured_logging() twice does not double-install handlers."""
    monkeypatch.setenv("ECHOLON_LOG_JSON", "1")
    from echolon._internal.structured_logging import install_structured_logging, _JsonFormatter
    import logging

    root = logging.getLogger()
    # Clean state for the test
    for h in list(root.handlers):
        root.removeHandler(h)

    install_structured_logging()
    install_structured_logging()

    json_handlers = [h for h in root.handlers if isinstance(h.formatter, _JsonFormatter)]
    assert len(json_handlers) == 1
```

- [ ] **Step 4: Run**

Run: `pytest tests/_internal/test_structured_logging.py -v`

Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add echolon/backtest/cli.py echolon/native/cli/ tests/_internal/test_structured_logging.py
git commit -m "feat(logging): install_structured_logging hook at CLI entry points"
```

---

## Task P3.3 — Demote per-contract / per-trial INFO spam to DEBUG

**Files:**
- Modify: `echolon/indicators/engine/processor.py`, `echolon/indicators/optimization/interday_regime_optimizer.py`, `echolon/backtest/engine/hooks/contract_aware/broker.py`

- [ ] **Step 1: Identify the spam sites (from the audits)**

- `echolon/indicators/engine/processor.py:215, 264` — per-contract "Processing" / "Complete" INFO.
- `echolon/indicators/optimization/interday_regime_optimizer.py:741, 833` — per-trial STARTED / COMPLETED INFO.
- `echolon/backtest/engine/hooks/contract_aware/broker.py:96, 131, 147, 333, 339, 343, 349, 375, 378, 410, 440` — per-contract cache-load / price-lookup INFO.

- [ ] **Step 2: Replace `logger.info(...)` with `logger.debug(...)` in-place**

For each line above, demote the level. Where a summary is useful, add a single INFO log at the end of the loop. Pattern:

```python
# Before (inside a 400-trial loop):
logger.info(f"[REGIME_OPTIMIZER] Trial {trial.number} STARTED | pid={pid}, thread={tid}")

# After:
logger.debug(f"[REGIME_OPTIMIZER] Trial {trial.number} STARTED | pid={pid}, thread={tid}")

# At the end of optimize() (outside the loop), one summary:
logger.info(
    f"[REGIME_OPTIMIZER] Optimization complete | n_trials={self.config.n_trials}, "
    f"rejected={len(self._degenerate_trials)}, best_score={study.best_value:.4f}"
)
```

Apply the same pattern to the `processor.py` contract loop and the `contract_aware/broker.py` price-lookup loop.

- [ ] **Step 3: Run full suite**

Run: `pytest -q`

Expected: green. Tests that capture logs may need `caplog.at_level(logging.DEBUG)` if they were relying on INFO-level capture of these specific messages. Fix those test captures as they surface.

- [ ] **Step 4: Commit**

```bash
git add echolon/indicators/engine/processor.py \
        echolon/indicators/optimization/interday_regime_optimizer.py \
        echolon/backtest/engine/hooks/contract_aware/broker.py
git commit -m "perf(logging): demote per-bar/per-trial INFO spam to DEBUG"
```

---

## Task P3.4 — Phase 3 marker commit

```bash
git commit --allow-empty -m "chore: phase 3 (structured logging + noise reduction) complete"
```

---

# PHASE 4 — Strategy-loader pre-flight validation

**Rationale:** Phase 1 wired STR-001..003, PRM-001, VAL-002 at their current raise sites. Phase 4 moves validation EARLIER — before the strategy module is loaded into the backtest engine — so every common strategy-author error (missing file, wrong class name, missing method, invalid signal enum, bad params structure) surfaces AT LOAD TIME with a catalog code. This is where LLMs hit the most errors.

## Task P4.1 — Preflight orchestrator

**Files:**
- Create: `echolon/strategy/preflight.py`
- Test: `tests/strategy/test_preflight.py` (new)

- [ ] **Step 1: Write the failing test**

Create `tests/strategy/test_preflight.py`:

```python
"""Preflight validation runs all strategy checks up-front and raises the first
catalog error encountered."""
from pathlib import Path
from textwrap import dedent

import pytest


def _make_valid_strategy(root: Path) -> None:
    """Write a minimal valid 7-file strategy tree."""
    (root / "entry.py").write_text(dedent("""
        from echolon.strategy.component import EntryComponent
        class Entry(EntryComponent):
            def evaluate(self, bar):
                return None
    """))
    (root / "exit.py").write_text(dedent("""
        from echolon.strategy.component import ExitComponent
        class Exit(ExitComponent):
            def evaluate(self, bar, position):
                return None
    """))
    (root / "risk.py").write_text(dedent("""
        from echolon.strategy.component import RiskComponent
        class Risk(RiskComponent):
            def evaluate(self, signal, portfolio):
                return signal
    """))
    (root / "sizer.py").write_text(dedent("""
        from echolon.strategy.component import SizerComponent
        class Sizer(SizerComponent):
            def size(self, signal, portfolio):
                return 0
    """))
    (root / "component.py").write_text("# marker file")
    (root / "strategy_params.py").write_text(dedent("""
        DEFAULT_PARAMS = {
            'entry_params': {'printlog': False},
            'exit_params':  {'printlog': False},
            'risk_params':  {'printlog': False},
            'sizer_params': {'printlog': False},
        }
    """))
    (root / "strategy_indicator_list.json").write_text('{}')


def test_preflight_valid_strategy_passes(tmp_path):
    _make_valid_strategy(tmp_path)
    from echolon.strategy.preflight import preflight

    # Should not raise
    preflight(tmp_path)


def test_preflight_missing_file_raises_str_001(tmp_path):
    _make_valid_strategy(tmp_path)
    (tmp_path / "sizer.py").unlink()

    from echolon.strategy.preflight import preflight
    from echolon.errors import StrategyStructureError

    with pytest.raises(StrategyStructureError) as exc:
        preflight(tmp_path)
    assert exc.value.code == "STR-001"


def test_preflight_missing_params_key_raises_prm_002(tmp_path):
    _make_valid_strategy(tmp_path)
    (tmp_path / "strategy_params.py").write_text(dedent("""
        DEFAULT_PARAMS = {
            'entry_params': {'printlog': False},
            # missing exit_params, risk_params, sizer_params
        }
    """))

    from echolon.strategy.preflight import preflight
    from echolon.errors import EchelonError

    with pytest.raises(EchelonError) as exc:
        preflight(tmp_path)
    assert exc.value.code == "PRM-002"


def test_preflight_missing_printlog_raises_prm_001(tmp_path):
    _make_valid_strategy(tmp_path)
    (tmp_path / "strategy_params.py").write_text(dedent("""
        DEFAULT_PARAMS = {
            'entry_params': {},  # missing printlog
            'exit_params':  {'printlog': False},
            'risk_params':  {'printlog': False},
            'sizer_params': {'printlog': False},
        }
    """))

    from echolon.strategy.preflight import preflight
    from echolon.errors import EchelonError

    with pytest.raises(EchelonError) as exc:
        preflight(tmp_path)
    assert exc.value.code == "PRM-001"
```

- [ ] **Step 2: Run to confirm failure**

Run: `pytest tests/strategy/test_preflight.py -v`

Expected: FAIL — `preflight` module doesn't exist.

- [ ] **Step 3: Create the preflight module**

Create `echolon/strategy/preflight.py`:

```python
"""Pre-load strategy validation.

Runs all cheap, file-level checks against a strategy directory BEFORE the
backtest or live engine tries to instantiate the strategy. Each check raises
the appropriate catalog code on failure so LLM callers get the most specific,
actionable error possible.

Order of checks (fail fast on the cheapest check):
    1. STR-001: all 7 required files present
    2. STR-002: each *.py exports the expected class name
    3. PRM-002: strategy_params.DEFAULT_PARAMS has all 4 component keys
    4. PRM-001: every component sub-dict contains 'printlog'
    (STR-003 is runtime-only, not preflight-checkable.)
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from echolon.errors import raise_error

REQUIRED_FILES = [
    "entry.py",
    "exit.py",
    "risk.py",
    "sizer.py",
    "component.py",
    "strategy_params.py",
    "strategy_indicator_list.json",
]

EXPECTED_CLASSES = {
    "entry.py": "Entry",
    "exit.py":  "Exit",
    "risk.py":  "Risk",
    "sizer.py": "Sizer",
}

REQUIRED_PARAM_KEYS = ("entry_params", "exit_params", "risk_params", "sizer_params")


def _check_required_files(strategy_dir: Path) -> None:
    missing = [f for f in REQUIRED_FILES if not (strategy_dir / f).exists()]
    if missing:
        raise_error(
            "STR-001",
            strategy_dir=str(strategy_dir),
            missing_files=", ".join(missing),
        )


def _check_required_classes(strategy_dir: Path) -> None:
    for file_name, expected_class in EXPECTED_CLASSES.items():
        file_path = strategy_dir / file_name
        spec = importlib.util.spec_from_file_location(
            f"_preflight_{file_path.stem}_{id(file_path)}",
            file_path,
        )
        module = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(module)
        except Exception as exc:
            raise_error(
                "STR-002",
                file=str(file_path),
                expected_class=expected_class,
                found_classes=f"<module failed to import: {exc}>",
            )
        if not hasattr(module, expected_class):
            found = [name for name in dir(module) if not name.startswith("_")]
            raise_error(
                "STR-002",
                file=str(file_path),
                expected_class=expected_class,
                found_classes=", ".join(found),
            )


def _check_params_structure(strategy_dir: Path) -> None:
    params_file = strategy_dir / "strategy_params.py"
    spec = importlib.util.spec_from_file_location("_preflight_params", params_file)
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        raise_error(
            "PRM-002",
            file=str(params_file),
            missing_keys=f"<import failed: {exc}>",
        )

    default = getattr(module, "DEFAULT_PARAMS", None)
    if not isinstance(default, dict):
        raise_error(
            "PRM-002",
            file=str(params_file),
            missing_keys="<DEFAULT_PARAMS missing or not a dict>",
        )

    missing_keys = [k for k in REQUIRED_PARAM_KEYS if k not in default]
    if missing_keys:
        raise_error(
            "PRM-002",
            file=str(params_file),
            missing_keys=", ".join(missing_keys),
        )

    # printlog per component
    for component_key in REQUIRED_PARAM_KEYS:
        sub = default[component_key]
        if not isinstance(sub, dict) or "printlog" not in sub:
            raise_error(
                "PRM-001",
                file=str(params_file),
                function="DEFAULT_PARAMS",
                component_key=component_key,
            )


def preflight(strategy_dir: Path | str) -> None:
    """Run all preflight checks against a strategy directory. Raises on
    the first failure; callers should surface the resulting EchelonError
    verbatim (its __str__ already renders what/why/fix/context/docs_url)."""
    strategy_dir = Path(strategy_dir)
    _check_required_files(strategy_dir)
    _check_required_classes(strategy_dir)
    _check_params_structure(strategy_dir)
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/strategy/test_preflight.py -v`

Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add echolon/strategy/preflight.py tests/strategy/test_preflight.py
git commit -m "feat(strategy): preflight() validates a strategy dir before load"
```

---

## Task P4.2 — Wire preflight into loader + backtest entry points

**Files:**
- Modify: `echolon/strategy/loader.py`, `echolon/backtest/runner.py`
- Test: `tests/strategy/test_preflight.py` (extend)

- [ ] **Step 1: Write the failing integration test**

Append to `tests/strategy/test_preflight.py`:

```python
def test_load_strategy_calls_preflight(tmp_path):
    """loader.load_strategy_from_dir must call preflight() before importing."""
    _make_valid_strategy(tmp_path)
    # Break the strategy: remove a required file
    (tmp_path / "risk.py").unlink()

    from echolon.strategy.loader import load_strategy_from_dir
    from echolon.errors import StrategyStructureError

    with pytest.raises(StrategyStructureError) as exc:
        load_strategy_from_dir(tmp_path)
    # STR-001 must fire before the loader attempts any import
    assert exc.value.code == "STR-001"
```

- [ ] **Step 2: Run, confirm failure mode (or already-passing since Phase 1 wired STR-001)**

Run: `pytest tests/strategy/test_preflight.py -v`

Phase 1 already wired STR-001 in the loader; this test should pass. But confirm the loader is going through `preflight()` not just the ad-hoc `REQUIRED_FILES` check.

- [ ] **Step 3: Update `loader.py` to call `preflight()` first**

At the top of `load_strategy_from_dir` (or equivalent entry function):

```python
from echolon.strategy.preflight import preflight


def load_strategy_from_dir(strategy_dir):
    strategy_dir = Path(strategy_dir)
    preflight(strategy_dir)  # raises STR-001/002, PRM-001/002 first
    # ... existing import logic
```

Remove the ad-hoc `REQUIRED_FILES` / `getattr` checks from `load_strategy_from_dir` — they are now in `preflight`.

- [ ] **Step 4: Run tests**

Run: `pytest tests/strategy/ -v`

Expected: green.

- [ ] **Step 5: Commit**

```bash
git add echolon/strategy/loader.py tests/strategy/test_preflight.py
git commit -m "refactor(strategy): loader delegates validation to preflight()"
```

---

## Task P4.3 — Signal enum validation at component-output boundary

**Files:**
- Modify: `echolon/strategy/schemas.py`
- Test: `tests/strategy/test_signal_validation.py` (new)

The audit noted `EntrySignalOutput` and `ExitSignalOutput` currently use `extra='allow'`, so an LLM that returns `signal='long'` (lowercase) silently fails downstream. Wire VAL-002 at the Pydantic validator layer.

- [ ] **Step 1: Write the failing test**

Create `tests/strategy/test_signal_validation.py`:

```python
"""Signal outputs with wrong enum casing must raise VAL-002 with actionable context."""
import pytest

from echolon.errors import ValidationError


def test_lowercase_signal_raises_val_002():
    from echolon.strategy.schemas import EntrySignalOutput

    with pytest.raises(ValidationError) as exc:
        EntrySignalOutput(signal="long", strength=0.8, type="entry", entry_reason="x")
    assert exc.value.code == "VAL-002"
    assert "long" in str(exc.value)
    assert "LONG" in str(exc.value)


def test_valid_signal_accepted():
    from echolon.strategy.schemas import EntrySignalOutput

    sig = EntrySignalOutput(signal="LONG", strength=0.8, type="entry", entry_reason="x")
    assert sig.signal == "LONG"
```

- [ ] **Step 2: Run, confirm failure**

Run: `pytest tests/strategy/test_signal_validation.py -v`

Expected: FAIL — current code uses Pydantic's Literal which raises `pydantic.ValidationError`, not `EchelonError`.

- [ ] **Step 3: Add pre-validator to schemas**

In `echolon/strategy/schemas.py`, import `raise_error` and add a `@field_validator` on the `signal` field of `EntrySignalOutput` and `ExitSignalOutput`:

```python
from echolon.errors import raise_error
from pydantic import field_validator

VALID_SIGNALS = {"LONG", "SHORT", "HOLD"}


class EntrySignalOutput(BaseModel):
    signal: str
    strength: float
    type: str
    entry_reason: str
    # ... other fields

    @field_validator("signal", mode="before")
    @classmethod
    def _validate_signal_enum(cls, v):
        if v not in VALID_SIGNALS:
            raise_error(
                "VAL-002",
                file="EntrySignalOutput",
                method="<signal field>",
                got=repr(v),
            )
        return v
```

Mirror in `ExitSignalOutput`.

- [ ] **Step 4: Run tests**

Run: `pytest tests/strategy/test_signal_validation.py -v`

Expected: 2 passed.

- [ ] **Step 5: Run full strategy suite**

Run: `pytest tests/strategy/ -q`

Expected: green.

- [ ] **Step 6: Commit**

```bash
git add echolon/strategy/schemas.py tests/strategy/test_signal_validation.py
git commit -m "feat(strategy): VAL-002 on invalid signal enum at EntrySignalOutput/ExitSignalOutput"
```

---

## Task P4.4 — Phase 4 marker commit

```bash
git commit --allow-empty -m "chore: phase 4 (strategy preflight) complete"
```

---

# PHASE 4B — Close LLM-author hot-path gaps

**Rationale:** Phases 0–4 covered the infrastructure + the biggest preflight payoffs. Four specific failure modes remain on the critical path when an LLM *authors* a strategy (vs. operates one). Each is a defined-but-dormant or single-file wire-up:

- **IND-001 (indicator casing mismatch)** — LLMs will write `rsi_14` in one file and `RSI_14` in another; the code is in the catalog but never raised.
- **VAL-001 + `extra='forbid'`** — Pydantic's `extra='allow'` silently accepts `EntrySignalOutput` missing required fields like `regime`, so strategies run with nonsense data. Tighten the schema.
- **IND-005 (missing OHLCV column in calculator)** — the 4–5 sites in `calculators/` that currently `raise ValueError("DataFrame must have 'datetime' column")` get a catalog code with shape/sample context.
- **DAT-001 wire** — `ohlcv_loader.load_ohlcv` still raises bare `FileNotFoundError`. Wire the existing DAT-001 catalog entry.

This phase is ~4 tasks, ~150 LOC. After it lands, every failure an LLM can trip while writing a strategy raises a catalog code with what/why/fix/context/docs_url.

## Task P4B.1 — IND-001 (indicator casing pre-flight)

**Files:**
- Modify: `echolon/strategy/preflight.py`
- Test: `tests/strategy/test_preflight_indicator_casing.py` (new)

The preflight should parse `strategy_indicator_list.json` and compare the declared indicator names against any references found in the strategy's `.py` files (string literals). Mismatches in casing raise IND-001.

- [ ] **Step 1: Write the failing test**

Create `tests/strategy/test_preflight_indicator_casing.py`:

```python
"""Preflight compares indicator names in code vs JSON; casing mismatch raises IND-001."""
import json
from pathlib import Path
from textwrap import dedent

import pytest

from echolon.errors import IndicatorError


def _make_strategy_with_indicator_use(root: Path, code_name: str, json_name: str):
    """Create a minimal strategy where entry.py references `code_name` as a
    string literal, but strategy_indicator_list.json declares `json_name`."""
    (root / "entry.py").write_text(dedent(f"""
        from echolon.strategy.component import EntryComponent
        class Entry(EntryComponent):
            def evaluate(self, bar):
                return bar.get({code_name!r})
    """))
    for name in ("exit.py", "risk.py", "sizer.py", "component.py"):
        (root / name).write_text("# stub")
    (root / "strategy_params.py").write_text(dedent("""
        DEFAULT_PARAMS = {
            'entry_params': {'printlog': False},
            'exit_params':  {'printlog': False},
            'risk_params':  {'printlog': False},
            'sizer_params': {'printlog': False},
        }
    """))
    (root / "strategy_indicator_list.json").write_text(json.dumps({
        "indicators": [{"name": json_name, "params": {}}]
    }))


def test_casing_mismatch_raises_ind_001(tmp_path):
    _make_strategy_with_indicator_use(tmp_path, code_name="RSI_14", json_name="rsi_14")

    from echolon.strategy.preflight import preflight

    with pytest.raises(IndicatorError) as exc:
        preflight(tmp_path)
    assert exc.value.code == "IND-001"
    assert "RSI_14" in str(exc.value)
    assert "rsi_14" in str(exc.value)


def test_matching_casing_passes(tmp_path):
    _make_strategy_with_indicator_use(tmp_path, code_name="rsi_14", json_name="rsi_14")

    from echolon.strategy.preflight import preflight

    # No raise — matching casing is fine
    preflight(tmp_path)
```

- [ ] **Step 2: Run**

Run: `pytest tests/strategy/test_preflight_indicator_casing.py -v`

Expected: both FAIL — preflight doesn't do this check yet.

- [ ] **Step 3: Extend preflight with the casing check**

In `echolon/strategy/preflight.py`, after `_check_params_structure`, add:

```python
import ast
import json as _json
import re as _re


def _collect_json_declared_indicators(strategy_dir: Path) -> set[str]:
    """Return the set of indicator names declared in strategy_indicator_list.json."""
    path = strategy_dir / "strategy_indicator_list.json"
    try:
        payload = _json.loads(path.read_text())
    except (_json.JSONDecodeError, OSError):
        return set()
    indicators = payload.get("indicators", [])
    names: set[str] = set()
    for entry in indicators:
        if isinstance(entry, dict) and "name" in entry:
            names.add(str(entry["name"]))
        elif isinstance(entry, str):
            names.add(entry)
    return names


def _collect_code_referenced_indicators(strategy_dir: Path) -> set[str]:
    """Heuristic: scan string literals in entry/exit/risk/sizer.py for tokens
    that look like indicator names (lowercase + digits + underscores, or all-caps)."""
    pattern = _re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")
    referenced: set[str] = set()
    for file_name in EXPECTED_CLASSES:  # entry.py, exit.py, risk.py, sizer.py
        path = strategy_dir / file_name
        if not path.exists():
            continue
        try:
            tree = ast.parse(path.read_text())
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                s = node.value
                if pattern.match(s) and len(s) >= 3:
                    referenced.add(s)
    return referenced


def _check_indicator_casing(strategy_dir: Path) -> None:
    """Raise IND-001 if any code reference exists whose lowercase form
    matches a JSON-declared indicator name but the casing differs."""
    declared = _collect_json_declared_indicators(strategy_dir)
    referenced = _collect_code_referenced_indicators(strategy_dir)
    declared_lower = {n.lower(): n for n in declared}
    for code_name in referenced:
        lower = code_name.lower()
        if lower in declared_lower and code_name != declared_lower[lower]:
            raise_error(
                "IND-001",
                code_name=code_name,
                json_name=declared_lower[lower],
            )
```

Append to the `preflight()` function body, after the `_check_params_structure` call:

```python
def preflight(strategy_dir: Path | str) -> None:
    strategy_dir = Path(strategy_dir)
    _check_required_files(strategy_dir)
    _check_required_classes(strategy_dir)
    _check_params_structure(strategy_dir)
    _check_indicator_casing(strategy_dir)  # NEW
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/strategy/test_preflight_indicator_casing.py -v`

Expected: 2 passed.

- [ ] **Step 5: Run the full strategy suite**

Run: `pytest tests/strategy/ -q`

Expected: green.

- [ ] **Step 6: Commit**

```bash
git add echolon/strategy/preflight.py tests/strategy/test_preflight_indicator_casing.py
git commit -m "feat(strategy): preflight raises IND-001 on indicator code/JSON casing mismatch"
```

---

## Task P4B.2 — VAL-001 + tighten signal-output schemas

**Files:**
- Modify: `echolon/strategy/schemas.py`
- Test: `tests/strategy/test_signal_validation.py` (extend)

Flip `EntrySignalOutput` and `ExitSignalOutput` to `extra='forbid'`, and add an explicit VAL-001 raise when required fields are missing. This is a **breaking change** for strategies that stuffed extra fields into the schema — accept it because echolon is pre-1.0 and the LLM-author case is the driver.

- [ ] **Step 1: Write the failing test**

Append to `tests/strategy/test_signal_validation.py`:

```python
def test_missing_required_field_raises_val_001():
    """EntrySignalOutput without `regime` / `entry_reason` raises VAL-001."""
    from echolon.strategy.schemas import EntrySignalOutput
    from echolon.errors import ValidationError

    with pytest.raises(ValidationError) as exc:
        # Intentionally omit 'entry_reason'
        EntrySignalOutput(signal="LONG", strength=0.8, type="entry")
    assert exc.value.code == "VAL-001"
    assert "entry_reason" in str(exc.value)


def test_extra_field_is_forbidden():
    """EntrySignalOutput rejects fields not declared on the schema."""
    from echolon.strategy.schemas import EntrySignalOutput
    import pydantic

    with pytest.raises((pydantic.ValidationError, ValueError)):
        EntrySignalOutput(
            signal="LONG",
            strength=0.8,
            type="entry",
            entry_reason="x",
            custom_unknown_field=42,
        )


def test_exit_signal_output_same_contract():
    from echolon.strategy.schemas import ExitSignalOutput
    from echolon.errors import ValidationError

    with pytest.raises(ValidationError) as exc:
        # Omit required fields
        ExitSignalOutput(signal="SHORT")
    assert exc.value.code == "VAL-001"
```

- [ ] **Step 2: Run**

Run: `pytest tests/strategy/test_signal_validation.py -v`

Expected: FAIL — current `extra='allow'` accepts extras + silent-default missing fields.

- [ ] **Step 3: Update `EntrySignalOutput` + `ExitSignalOutput`**

In `echolon/strategy/schemas.py`:

```python
from pydantic import BaseModel, ConfigDict, model_validator
from echolon.errors import raise_error


class EntrySignalOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    signal: str
    strength: float
    type: str
    entry_reason: str
    # ... keep existing required fields

    @model_validator(mode="before")
    @classmethod
    def _check_required_fields(cls, values):
        if not isinstance(values, dict):
            return values
        missing = [f for f in cls.model_fields if f not in values]
        if missing:
            raise_error(
                "VAL-001",
                file="EntrySignalOutput",
                method="__init__",
                missing=", ".join(missing),
            )
        return values
```

Apply the same pattern to `ExitSignalOutput`.

- [ ] **Step 4: Run tests**

Run: `pytest tests/strategy/test_signal_validation.py -v`

Expected: all pass.

- [ ] **Step 5: Run full strategy suite**

Run: `pytest tests/strategy/ -q`

Expected: green. If any existing test constructs `EntrySignalOutput` with extra fields or missing fields (it shouldn't if the schemas are honestly enforced), update those tests — they were relying on laxity.

- [ ] **Step 6: Commit**

```bash
git add echolon/strategy/schemas.py tests/strategy/test_signal_validation.py
git commit -m "feat(strategy): VAL-001 + extra='forbid' on signal-output schemas"
```

---

## Task P4B.3 — IND-005: calculator missing-column checks

**Files:**
- Modify: `echolon/errors.py` (add IND-005)
- Modify: `echolon/indicators/calculators/intraday/indicators.py`, `echolon/indicators/calculators/intraday/market_context.py`, and any other calculator with a `raise ValueError("DataFrame must have 'X' column")` pattern
- Test: `tests/indicators/test_calculator_column_checks.py` (new)

- [ ] **Step 1: Add IND-005 to the catalog**

In `echolon/errors.py`, append to `ERROR_CATALOG`:

```python
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
```

- [ ] **Step 2: Write the failing test**

Create `tests/indicators/test_calculator_column_checks.py`:

```python
"""Calculator column-contract violations raise IND-005 with full context."""
import pandas as pd
import pytest

from echolon.errors import IndicatorError


def test_intraday_indicator_missing_trading_date_raises_ind_005():
    """An intraday calculator receiving a DataFrame without 'trading_date'
    raises IND-005, not a bare ValueError."""
    from echolon.indicators.calculators.intraday import indicators

    # Construct a DataFrame missing 'trading_date'
    bad_df = pd.DataFrame({"open": [1, 2], "close": [2, 3]})

    with pytest.raises(IndicatorError) as exc:
        indicators._require_columns(bad_df, ["trading_date"], calculator="some_intraday_calc")
    assert exc.value.code == "IND-005"
    assert "trading_date" in str(exc.value)


def test_market_context_missing_datetime_raises_ind_005():
    from echolon.indicators.calculators.intraday import market_context

    bad_df = pd.DataFrame({"open": [1], "close": [2]})

    with pytest.raises(IndicatorError) as exc:
        market_context._require_columns(bad_df, ["datetime"], calculator="market_context")
    assert exc.value.code == "IND-005"
```

- [ ] **Step 3: Run, confirm failure**

Run: `pytest tests/indicators/test_calculator_column_checks.py -v`

Expected: FAIL — `_require_columns` helpers don't exist yet.

- [ ] **Step 4: Add a shared `_require_columns` helper**

Add to `echolon/indicators/calculators/intraday/indicators.py` (top-level, module-scope):

```python
import pandas as pd
from echolon.errors import raise_error


def _require_columns(df: pd.DataFrame, required: list[str], *, calculator: str) -> None:
    """Raise IND-005 if any `required` column is missing from `df`."""
    present = list(df.columns)
    for col in required:
        if col not in present:
            raise_error(
                "IND-005",
                calculator=calculator,
                missing_column=col,
                required_columns=", ".join(required),
                present_columns=", ".join(present) if present else "<empty>",
            )
```

Copy the same helper into `echolon/indicators/calculators/intraday/market_context.py` (local copy is OK — the helper is small and avoids a cross-module import). Alternatively, extract into `echolon/indicators/calculators/_utils.py` if you prefer one source — either works.

- [ ] **Step 5: Replace the bare `raise ValueError("DataFrame must have 'X' column")` sites**

For each site flagged by the audit (at least `intraday/indicators.py:45` and `intraday/market_context.py:174`, and any siblings), replace:

```python
# BEFORE
if 'datetime' not in df.columns:
    raise ValueError("DataFrame must have 'datetime' column")
```

with:

```python
# AFTER
_require_columns(df, ['datetime'], calculator=<this_function_name>)
```

Grep to find the pattern:

```bash
rg -n 'raise ValueError\("DataFrame must have' echolon/indicators/calculators/
```

and convert every hit.

- [ ] **Step 6: Run tests**

Run: `pytest tests/indicators/test_calculator_column_checks.py tests/indicators/ -v`

Expected: green.

- [ ] **Step 7: Commit**

```bash
git add echolon/errors.py echolon/indicators/calculators/ tests/indicators/test_calculator_column_checks.py
git commit -m "feat(indicators): IND-005 on calculator missing-column contracts"
```

---

## Task P4B.4 — DAT-001 wire in `ohlcv_loader`

**Files:**
- Modify: `echolon/data/loaders/ohlcv_loader.py`
- Test: `tests/data/test_ohlcv_loader_dat_001.py` (new)

- [ ] **Step 1: Write the failing test**

Create `tests/data/test_ohlcv_loader_dat_001.py`:

```python
"""ohlcv_loader raises DAT-001 (not bare FileNotFoundError) when the file is missing."""
import pytest

from echolon.errors import DataError


def test_load_ohlcv_missing_file_raises_dat_001(tmp_path):
    from echolon.data.loaders.ohlcv_loader import load_ohlcv

    with pytest.raises(DataError) as exc:
        load_ohlcv(market="SHFE", asset="aluminum", market_data_dir=tmp_path)
    assert exc.value.code == "DAT-001"
    assert "aluminum" in str(exc.value) or "sort_by_date.csv" in str(exc.value)


def test_load_contract_ohlcv_missing_file_returns_none(tmp_path):
    """For contract-level loads, returning None for "contract not found" is
    acceptable (many contracts don't have files); only the primary load_ohlcv
    gets DAT-001 treatment."""
    from echolon.data.loaders.ohlcv_loader import load_contract_ohlcv

    result = load_contract_ohlcv(
        market="SHFE",
        asset="aluminum",
        contract="al9999",
        market_data_dir=tmp_path,
    )
    assert result is None
```

- [ ] **Step 2: Run**

Run: `pytest tests/data/test_ohlcv_loader_dat_001.py -v`

Expected: FAIL — currently raises bare `FileNotFoundError`.

- [ ] **Step 3: Update `load_ohlcv`**

In `echolon/data/loaders/ohlcv_loader.py`, replace the bare `raise FileNotFoundError(...)` at the end of `load_ohlcv`:

```python
from echolon.errors import raise_error

# Inside load_ohlcv(...) after constructing data_file:
if not os.path.exists(data_file):
    logger.error(f"[OHLCV_LOADER] File not found: {data_file}")
    raise_error(
        "DAT-001",
        path=data_file,
        field="market_data_dir",
    )
```

Leave `load_contract_ohlcv` unchanged — returning `None` on a missing single-contract file is intentional (caller iterates over many contracts).

- [ ] **Step 4: Run tests**

Run: `pytest tests/data/test_ohlcv_loader_dat_001.py -v`

Expected: 2 passed.

- [ ] **Step 5: Run full data suite**

Run: `pytest tests/data/ -q`

Expected: green.

- [ ] **Step 6: Commit**

```bash
git add echolon/data/loaders/ohlcv_loader.py tests/data/test_ohlcv_loader_dat_001.py
git commit -m "feat(data): ohlcv_loader.load_ohlcv raises DAT-001 (was bare FileNotFoundError)"
```

---

## Task P4B.5 — Extend AST regression

**Files:**
- Modify: `tests/test_error_catalog_compliance.py`

- [ ] **Step 1: Add the new sites to the MIGRATED_SUBSYSTEMS list**

In `tests/test_error_catalog_compliance.py`, extend:

```python
MIGRATED_SUBSYSTEMS = [
    # ... existing entries
    "strategy/schemas.py",
    "data/loaders/ohlcv_loader.py",
    "indicators/calculators/intraday/indicators.py",
    "indicators/calculators/intraday/market_context.py",
]
```

- [ ] **Step 2: Run**

Run: `pytest tests/test_error_catalog_compliance.py -v`

Expected: PASS if all P4B tasks landed cleanly.

- [ ] **Step 3: Commit**

```bash
git add tests/test_error_catalog_compliance.py
git commit -m "test: extend AST regression to the Phase 4B migrated files"
```

---

## Task P4B.6 — Phase 4B marker commit

```bash
git commit --allow-empty -m "chore: phase 4B (LLM-author hot-path gaps closed) complete"
```

---

# PHASE 5 — Docs integration

**Rationale:** `raise_error` already emits `docs_url=https://echolon.dev/docs/errors/{code}`, but no such page exists. Phase 5 publishes one markdown file per code to the repo's `docs/errors/` tree; the hosted docs build consumes it.

## Task P5.1 — Per-code docs page template

**Files:**
- Create: `docs/errors/_template.md`

- [ ] **Step 1: Create the template**

Create `docs/errors/_template.md`:

```markdown
# {CODE}: {WHAT}

## Why this error fires

{WHY — one paragraph from ERROR_CATALOG[code]["why"]}

## Fix

{FIX — prose version of the fix_template, with any typical variable values}

## Example

```python
# The code that triggers this error:
# (snippet reproduced from an LLM author's mistake)
```

```python
# The corrected version:
# (showing the exact change)
```

## Related codes

- {RELATED-001}: {short reason}
- {RELATED-002}: {short reason}

## See also

- [CONFIG_REFERENCE](../CONFIG_REFERENCE.md)
- [COMPONENT_GUIDE](../COMPONENT_GUIDE.md)
```

- [ ] **Step 2: Commit**

```bash
mkdir -p /home/yzj/projects/quantitive_trading/echolon/docs/errors
git add docs/errors/_template.md
git commit -m "docs(errors): add per-code page template"
```

---

## Task P5.2 — Generate one docs page per code

**Files:**
- Create: `docs/errors/{code}.md` for every code in `ERROR_CATALOG`
- Modify: `docs/CONFIG_REFERENCE.md` (link the index)

- [ ] **Step 1: Enumerate codes**

```bash
python -c "from echolon.errors import ERROR_CATALOG; print('\n'.join(sorted(ERROR_CATALOG.keys())))"
```

Expected output (25 codes after Phase 1 + Phase 4B):

```
BT-001, BT-002, BT-003,
CFG-001, CFG-002,
DAT-001, DAT-002, DAT-003, DAT-004,
IND-001, IND-002, IND-003, IND-004, IND-005,
LIV-001, LIV-002, LIV-003,
PRM-001, PRM-002,
STR-001, STR-002, STR-003,
VAL-001, VAL-002, VAL-003
```

- [ ] **Step 2: Create each docs page**

For EACH code, create `docs/errors/{code}.md`. Use the template; fill in the placeholders by copying from `ERROR_CATALOG[code]`. For the "Example" sections, write one before/after code snippet that illustrates the typical LLM-author mistake. Below is a worked example for `STR-001`:

`docs/errors/STR-001.md`:

```markdown
# STR-001: Strategy directory missing required file

## Why this error fires

Every Echolon strategy needs 7 files for the loader to work:

- `entry.py`, `exit.py`, `risk.py`, `sizer.py` — the four component files
- `component.py` — base-class imports
- `strategy_params.py` — `DEFAULT_PARAMS` dict
- `strategy_indicator_list.json` — declared indicators

The loader refuses to proceed with fewer than 7 because skipping validation
upfront would cause a confusing crash later in the backtest.

## Fix

Add the missing file listed in `context.missing_files`. A minimal working
`sizer.py`, for example:

```python
from echolon.strategy.component import SizerComponent

class Sizer(SizerComponent):
    def size(self, signal, portfolio):
        return 1
```

## Example

```
Error: [STR-001] Strategy directory missing required file
  Why:     Every Echolon strategy needs 7 files for the loader to work.
  Fix:     Add the missing file to /tmp/my_strategy:
             missing: sizer.py
             See `echolon init-strategy --template minimal` for a working example.
  Context: {'strategy_dir': '/tmp/my_strategy', 'missing_files': 'sizer.py'}
  Docs:    https://echolon.dev/docs/errors/STR-001
```

## Related codes

- [STR-002](STR-002.md): file exists but the expected class is missing.
- [STR-003](STR-003.md): class exists but a required method is not implemented.

## See also

- [COMPONENT_GUIDE](../COMPONENT_GUIDE.md)
- [CONFIG_REFERENCE](../CONFIG_REFERENCE.md)
```

Repeat for every code. This is the bulk of Phase 5 — about 24 similar files, each 30–50 lines. Reuse the Example-block format.

- [ ] **Step 3: Add a codes index**

Create `docs/errors/README.md`:

```markdown
# Echolon Error Catalog

Each page documents one error code with what/why/fix plus a worked example
showing the typical LLM-author mistake. `EchelonError.docs_url` points here.

## Strategy structure (STR-*)
- [STR-001](STR-001.md): Missing required file
- [STR-002](STR-002.md): Class not found
- [STR-003](STR-003.md): Method not implemented

## Parameter framework (PRM-*)
- [PRM-001](PRM-001.md): Missing `printlog`
- [PRM-002](PRM-002.md): Params structure mismatch

## Component signal validation (VAL-*)
- [VAL-001](VAL-001.md): Missing required field
- [VAL-002](VAL-002.md): Invalid signal enum value
- [VAL-003](VAL-003.md): Signature mismatch

## Indicators (IND-*)
- [IND-001](IND-001.md): Name casing mismatch
- [IND-002](IND-002.md): Undeclared indicator
- [IND-003](IND-003.md): All-NaN column
- [IND-004](IND-004.md): Degenerate regime optimizer result
- [IND-005](IND-005.md): Calculator missing required OHLCV column

## Data loading (DAT-*)
- [DAT-001](DAT-001.md): Required OHLCV file not found
- [DAT-002](DAT-002.md): Corrupt state JSON
- [DAT-003](DAT-003.md): Main contract data missing
- [DAT-004](DAT-004.md): Empty calendar

## Backtest (BT-*)
- [BT-001](BT-001.md): Strategy on_bar exception
- [BT-002](BT-002.md): Zero trades
- [BT-003](BT-003.md): Optuna constraint violation

## Live (LIV-*)
- [LIV-001](LIV-001.md): Broker unavailable
- [LIV-002](LIV-002.md): Order rejected
- [LIV-003](LIV-003.md): QMT callback error

## Config (CFG-*)
- [CFG-001](CFG-001.md): end_date before start_date
- [CFG-002](CFG-002.md): Required directory missing
```

- [ ] **Step 4: Write a test that every catalog code has a docs page**

Create `tests/test_error_docs_coverage.py`:

```python
"""Every code in ERROR_CATALOG has a corresponding docs/errors/{code}.md page."""
from pathlib import Path

from echolon.errors import ERROR_CATALOG


def test_every_code_has_docs_page():
    repo_root = Path(__file__).parent.parent
    docs_dir = repo_root / "docs" / "errors"
    missing = [code for code in ERROR_CATALOG if not (docs_dir / f"{code}.md").exists()]
    assert not missing, f"Catalog codes missing docs pages: {missing}"
```

- [ ] **Step 5: Run**

Run: `pytest tests/test_error_docs_coverage.py -v`

Expected: PASS when all 24 pages are present.

- [ ] **Step 6: Commit**

```bash
git add docs/errors/ tests/test_error_docs_coverage.py
git commit -m "docs(errors): per-code pages + codes index + coverage regression test"
```

---

## Task P5.3 — Cross-link from log messages to docs

**Files:**
- Modify: `echolon/errors.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/native/test_errors.py`:

```python
def test_echolon_error_str_includes_docs_url():
    from echolon.errors import raise_error
    try:
        raise_error("STR-001", strategy_dir="/tmp/x", missing_files="sizer.py")
    except Exception as exc:
        s = str(exc)
        assert "docs/errors/STR-001" in s or "echolon.dev/docs/errors/STR-001" in s
```

- [ ] **Step 2: Run to confirm it already passes**

Run: `pytest tests/native/test_errors.py::test_echolon_error_str_includes_docs_url -v`

`EchelonError.__str__` already interpolates `docs_url` — the test should pass against existing code.

- [ ] **Step 3: Commit the test only**

```bash
git add tests/native/test_errors.py
git commit -m "test(errors): regression lock for docs_url in EchelonError.__str__"
```

---

## Task P5.4 — Phase 5 marker commit

```bash
git commit --allow-empty -m "chore: phase 5 (docs integration) complete"
```

---

# Final verification

## Task F.1 — Sweep

- [ ] **Step 1: Run everything**

```bash
cd /home/yzj/projects/quantitive_trading/echolon
pytest -q
```

Expected: all green.

- [ ] **Step 2: Bare-raise audit across all migrated subsystems**

```bash
pytest tests/test_error_catalog_compliance.py -v
```

Expected: pass.

- [ ] **Step 3: Docs coverage**

```bash
pytest tests/test_error_docs_coverage.py -v
```

Expected: pass.

- [ ] **Step 4: Structured-logging smoke**

```bash
cd /tmp && ECHOLON_LOG_JSON=1 python -c "
from echolon._internal.structured_logging import install_structured_logging
install_structured_logging()
import logging
logging.getLogger('echolon.smoke').error('hello')
"
```

Expected: a single JSON-lines record on stderr containing `"code": null, "level": "ERROR", "message": "hello", "module": "echolon.smoke"`.

- [ ] **Step 5: Final empty-commit marker**

```bash
git commit --allow-empty -m "chore: llm-debuggability migration complete"
```

---

# Risks & rollback

- **Risk: A downstream test expected a bare exception type.** Every Phase 1.2–1.6 task runs the full suite; if a fix flips an unrelated test from green to red, pause and update that test to expect the `EchelonError` subclass.
- **Risk: Pydantic versions differ on `@field_validator` signature.** Task P4.3 assumes Pydantic v2. Confirm `echolon/strategy/schemas.py` already uses v2-style validators before editing (the other configs in the repo use v2).
- **Risk: `_JsonFormatter` swallows a non-JSON-serializable `extra` field.** The `repr(value)` fallback avoids a crash but obscures data. If you notice a key logged as `"<object at 0x...>"`, teach the caller to pass a simpler type.
- **Rollback: Every phase is a marker commit.** `git reset --hard phase-N-marker` rolls back cleanly. Phase 1's subsystem tasks (P1.2..P1.6) can be reverted independently because they each commit their tests alongside.

# Open questions (resolve before starting, or deliberately defer)

1. **Do we ship `BT-*` under a new `BacktestError` subclass, or keep them attached to `EchelonError` directly?** Phase 1 proposes the latter for simplicity; subclasses can be added in a follow-up without breaking callers.
2. **Should structured logging default-on for CLI entry points?** Currently it's opt-in via env var. Consider flipping the default for `echolon backtest`/`echolon live` CLIs in a future release once the JSON format stabilizes.
3. **Vendor-error translation layer for miniQMT / CCXT** — deliberately scoped out of this plan because it concerns live operators, not LLM strategy authors. Needs its own design phase once a second broker (CCXT) is actually implemented.
4. **Exhaustive bare-raise conversion for orchestration code** (WFA window tagging, portfolio_runner per-slot error isolation, MFE/MAE silent defaults, backtest_runner/backtest_runner legacy bare raises) — these are operator-facing, not strategy-author-facing. Deliberately deferred; the AST regression test in P1.7 does NOT guard these files, so adding catalog codes to them later won't be blocked.
