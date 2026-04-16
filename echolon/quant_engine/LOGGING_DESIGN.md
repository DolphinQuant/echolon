# Quant Engine Logging Architecture Design

**Date**: 2025-01-09
**Purpose**: Systematic logging for debugger_agent bug detection and developer debugging
**Status**: Design Document

---

## Executive Summary

The quant_engine module requires a **dual-mode logging architecture** that:

1. **Debug/Best Trial Mode**: Provides detailed bar-by-bar visibility into strategy decisions to understand WHY trades are or aren't being executed
2. **Optimization Mode**: Silences backtest noise, highlights Optuna progress, trial status, and critical errors only

### Key Requirements

| Requirement | Debug Mode | Optimization Mode |
|-------------|------------|-------------------|
| Entry signal decisions | Per-bar logging | Silent |
| Exit signal decisions | Per-bar logging | Silent |
| Risk check results | Per-bar logging | Silent |
| Position sizing | Per-bar logging | Silent |
| Trade execution | Detailed | Silent |
| Optuna progress | N/A | Every 25 trials |
| Trial completion | N/A | WARNING level |
| Errors | Full traceback | Classification + message |
| SUCCESS/FAILURE markers | CRITICAL level | CRITICAL level |

---

## 1. Log Level Strategy

### Level Hierarchy

```
CRITICAL → SUCCESS/FAILURE markers, final results (ALWAYS visible)
ERROR    → Critical bugs, hard breaks (ALWAYS visible)
WARNING  → Optuna progress, recoverable errors (optimization + debug)
INFO     → Workflow milestones, component summaries (debug/best_trial only)
DEBUG    → Bar-level details, calculations (debug only)
```

### Context-Based Suppression

```python
# optimization mode
ROOT_LEVEL = WARNING
BACKTEST_COMPONENTS = ERROR  # Entry, Exit, Risk, Sizer - SILENT
OPTUNA_COMPONENTS = WARNING  # Progress visible

# debug mode
ROOT_LEVEL = DEBUG
BACKTEST_COMPONENTS = DEBUG  # Full visibility
OPTUNA_COMPONENTS = N/A

# best_trial mode
ROOT_LEVEL = INFO
BACKTEST_COMPONENTS = INFO   # Key milestones only
OPTUNA_COMPONENTS = N/A
```

---

## 2. Message Format Standard

### Universal Format

```
[{CONTEXT}] {Component} | {STATUS} | {key1}={value1}, {key2}={value2}
```

### Context Tags
- `DEBUG` - Single backtest with full logging
- `BEST_TRIAL` - Single backtest with optimized params
- `OPTIMIZATION` - Optuna optimization run

### Status Tags
- `START` - Workflow/operation beginning
- `PROGRESS` - Intermediate status update
- `SUCCESS` - Successful completion
- `FAILURE` - Failed completion
- `INFO` - Informational message
- `DECISION` - Strategy decision point (entry/exit/risk)
- `ERROR` - Error occurred
- `RESULT` - Final metrics summary

### Examples

```python
# Workflow markers
"[DEBUG] Backtest | START | market=SHFE, instrument=aluminum, bars=5000"
"[DEBUG] Backtest | SUCCESS | trades=47, sharpe=1.25, return=23.5%"
"[DEBUG] Backtest | FAILURE | error=No trades executed"

# Component decisions
"[DEBUG] Entry | DECISION | signal=LONG, willr=-85, strength=0.85, reason=oversold"
"[DEBUG] Entry | DECISION | signal=HOLD, willr=-45, reason=not_oversold"
"[DEBUG] Exit | DECISION | should_exit=True, close=10450, stop=10475, reason=stop_hit"
"[DEBUG] Risk | DECISION | can_trade=False, drawdown=13.5%, threshold=12%, reason=drawdown_limit"
"[DEBUG] Sizer | DECISION | size=5, equity=100000, risk_pct=1%, stop_dist=50"

# Optimization progress
"[OPTIMIZATION] Optuna | PROGRESS | 25/100 (25%), best_sharpe=1.34, ETA=8.5min"
"[OPTIMIZATION] Optuna | TRIAL_COMPLETE | trial=42, sharpe=1.25, trades=47, status=OK"
"[OPTIMIZATION] Optuna | TRIAL_FAILED | trial=43, error=KeyError: 'indicator_x'"
"[OPTIMIZATION] Optuna | SUCCESS | trials=100, best_trial=67, best_sharpe=1.45"
```

---

## 3. Component-Specific Logging Design

### 3.1 BacktestRunner (Debug/Best Trial Mode)

**File**: `backtest/engine/backtest_runner.py`

```python
# Workflow markers (CRITICAL - always visible)
log_workflow_start("debug", "Backtest", market=self.market, instrument=self.instrument)

# Data loading (INFO - debug/best_trial only)
logger.info(f"[{context}] DataLoad | INFO | rows={len(indicators)}, "
           f"range={start_date} to {end_date}")

# Engine creation (INFO)
logger.info(f"[{context}] Engine | INFO | market_adapter={adapter_type}, "
           f"frequency={freq_context}, hooks={hooks_list}")

# Execution (INFO)
logger.info(f"[{context}] Execution | START | strategy={strategy_name}")

# Results (CRITICAL - always visible)
log_result_summary(context, "Backtest",
                   sharpe=results.sharpe_ratio,
                   total_return=results.total_return,
                   max_drawdown=results.max_drawdown,
                   num_trades=results.total_trades)

# Zero trades detection (WARNING - important for debugging)
if results.total_trades == 0:
    logger.warning(f"[{context}] Backtest | WARNING | Zero trades executed! "
                   "Check entry conditions and risk filters.")
```

### 3.2 BacktraderStrategyBridge (Debug Mode)

**File**: `backtest/engine/backtrader_strategy.py`

```python
def next(self):
    """Called on each bar - main entry point for strategy logic."""
    self._bar_count += 1

    # Progress logging every 500 bars (INFO level)
    if self._bar_count % 500 == 0:
        logger.info(f"[DEBUG] Strategy | PROGRESS | bar={self._bar_count}, "
                   f"date={self.data.datetime.date(0)}, position={self.position.size}")

    # Delegate to platform-agnostic strategy
    self._agnostic_strategy.on_bar()

def notify_trade(self, trade):
    """Handle trade notifications."""
    if not trade.isclosed:
        return

    self._trade_count += 1

    # Always log trade completion (INFO level)
    pnl_status = "WIN" if trade.pnlcomm > 0 else "LOSS"
    logger.info(f"[DEBUG] Trade | CLOSED | #{self._trade_count}, "
               f"pnl={trade.pnlcomm:.2f}, status={pnl_status}, "
               f"bars_held={trade.barlen}")
```

### 3.3 BaseStrategy - Entry Decision (Debug Mode)

**File**: `core/base/base_strategy.py`

```python
def _process_entry(self) -> None:
    """Process entry logic when no position exists."""
    # Get entry signal
    entry_output = self.entry_rule.generate_signal()

    # Log entry decision (DEBUG level - only in debug mode)
    if should_log_details(self._run_context):
        self._log_entry_decision(entry_output)

    # ... rest of logic

def _log_entry_decision(self, entry_output: EntrySignalOutput) -> None:
    """Log entry signal decision with diagnostic details."""
    signal_name = entry_output.signal.name if entry_output.signal else "NONE"

    # Build diagnostic message
    diagnostics = []
    if hasattr(entry_output, 'willr_value'):
        diagnostics.append(f"willr={entry_output.willr_value:.1f}")
    if hasattr(entry_output, 'session_phase'):
        diagnostics.append(f"session={entry_output.session_phase}")
    if hasattr(entry_output, 'bars_from_open'):
        diagnostics.append(f"bar_of_session={entry_output.bars_from_open}")

    diag_str = ", ".join(diagnostics) if diagnostics else "no_diagnostics"

    logger.debug(f"[DEBUG] Entry | DECISION | signal={signal_name}, "
                f"strength={entry_output.strength:.2f}, {diag_str}, "
                f"reason={entry_output.reason or 'none'}")
```

### 3.4 BaseStrategy - Exit Decision (Debug Mode)

```python
def _process_exit(self) -> None:
    """Process exit logic when position exists."""
    exit_output = self.exit_rule.should_exit()

    # Log exit decision (DEBUG level)
    if should_log_details(self._run_context):
        self._log_exit_decision(exit_output)

    # ... rest of logic

def _log_exit_decision(self, exit_output: ExitSignalOutput) -> None:
    """Log exit signal decision with stop details."""
    current_price = self.market_data.get_close()

    diagnostics = []
    if hasattr(exit_output, 'stop_price'):
        diagnostics.append(f"stop={exit_output.stop_price:.2f}")
        diagnostics.append(f"distance={current_price - exit_output.stop_price:.2f}")
    if hasattr(exit_output, 'highest_high'):
        diagnostics.append(f"high_water={exit_output.highest_high:.2f}")
    if hasattr(exit_output, 'atr_value'):
        diagnostics.append(f"atr={exit_output.atr_value:.2f}")

    diag_str = ", ".join(diagnostics) if diagnostics else "no_diagnostics"

    logger.debug(f"[DEBUG] Exit | DECISION | should_exit={exit_output.should_exit}, "
                f"close={current_price:.2f}, {diag_str}, "
                f"reason={exit_output.reason or 'hold'}")
```

### 3.5 BaseStrategy - Risk Decision (Debug Mode)

```python
def _check_risk(self) -> bool:
    """Check if trading is allowed by risk manager."""
    risk_output = self.risk_manager.can_trade()

    # Log risk decision (DEBUG level)
    if should_log_details(self._run_context):
        self._log_risk_decision(risk_output)

    return risk_output.can_trade

def _log_risk_decision(self, risk_output: RiskOutput) -> None:
    """Log risk check with metrics."""
    equity = self.portfolio.get_equity()

    diagnostics = []
    if hasattr(risk_output, 'drawdown_pct'):
        diagnostics.append(f"dd={risk_output.drawdown_pct:.2f}%")
    if hasattr(risk_output, 'session_loss_pct'):
        diagnostics.append(f"session_loss={risk_output.session_loss_pct:.2f}%")
    if hasattr(risk_output, 'equity_peak'):
        diagnostics.append(f"peak={risk_output.equity_peak:.0f}")

    diag_str = ", ".join(diagnostics) if diagnostics else "no_diagnostics"

    # Only log at DEBUG when trading allowed, WARNING when blocked
    if risk_output.can_trade:
        logger.debug(f"[DEBUG] Risk | DECISION | can_trade=True, equity={equity:.0f}, {diag_str}")
    else:
        logger.warning(f"[DEBUG] Risk | BLOCKED | can_trade=False, equity={equity:.0f}, "
                      f"{diag_str}, reason={risk_output.reason}")
```

### 3.6 BaseStrategy - Sizer Decision (Debug Mode)

```python
def _calculate_position_size(self, entry_output: EntrySignalOutput) -> int:
    """Calculate position size for entry."""
    sizer_output = self.position_sizer.calculate_size(entry_output)

    # Log sizing decision (DEBUG level)
    if should_log_details(self._run_context):
        self._log_sizer_decision(sizer_output)

    return sizer_output.position_size

def _log_sizer_decision(self, sizer_output: SizerOutput) -> None:
    """Log position sizing calculation."""
    equity = self.portfolio.get_equity()

    diagnostics = []
    if hasattr(sizer_output, 'risk_per_contract'):
        diagnostics.append(f"risk_per_contract={sizer_output.risk_per_contract:.2f}")
    if hasattr(sizer_output, 'stop_distance'):
        diagnostics.append(f"stop_dist={sizer_output.stop_distance:.2f}")
    if hasattr(sizer_output, 'raw_size'):
        diagnostics.append(f"raw={sizer_output.raw_size:.2f}")

    diag_str = ", ".join(diagnostics) if diagnostics else "no_diagnostics"

    logger.debug(f"[DEBUG] Sizer | DECISION | size={sizer_output.position_size}, "
                f"equity={equity:.0f}, {diag_str}")
```

### 3.7 OptunaOptimizer (Optimization Mode)

**File**: `backtest/optimization/optuna_study.py`

```python
def run(self, indicators, trading_calendar_df, study_name, indicator_metadata):
    """Run optimization study."""

    # Start marker (CRITICAL - always visible)
    log_workflow_start("optimization", "Optuna",
                      trials=self.n_trials,
                      target=self.optimization_target,
                      workers=self._get_worker_count())

    # Progress callback for trials
    def progress_callback(study, trial):
        """Log progress every 25 trials."""
        trial_num = trial.number + 1

        # Always log trial completion status (WARNING level)
        if trial.state == optuna.trial.TrialState.COMPLETE:
            metrics = trial.user_attrs
            logger.warning(f"[OPTIMIZATION] Trial | COMPLETE | #{trial_num}, "
                          f"sharpe={metrics.get('sharpe_ratio', 0):.3f}, "
                          f"trades={metrics.get('total_trades', 0)}")
        elif trial.state == optuna.trial.TrialState.FAIL:
            logger.warning(f"[OPTIMIZATION] Trial | FAILED | #{trial_num}, "
                          f"error={trial.user_attrs.get('error_message', 'unknown')}")

        # Progress milestone every 25 trials
        if trial_num % 25 == 0 or trial_num == self.n_trials:
            completed = len([t for t in study.trials if t.state == optuna.trial.TrialState.COMPLETE])
            failed = len([t for t in study.trials if t.state == optuna.trial.TrialState.FAIL])
            best_value = study.best_value if study.best_trial else 0

            elapsed = time.time() - self.start_time
            rate = trial_num / elapsed if elapsed > 0 else 0
            eta = (self.n_trials - trial_num) / rate if rate > 0 else 0

            logger.warning(f"[OPTIMIZATION] Optuna | PROGRESS | "
                          f"{trial_num}/{self.n_trials} ({100*trial_num/self.n_trials:.0f}%), "
                          f"completed={completed}, failed={failed}, "
                          f"best_sharpe={best_value:.3f}, "
                          f"ETA={format_time_seconds(eta)}")

    # Run optimization
    study.optimize(objective_func, n_trials=self.n_trials, callbacks=[progress_callback])

    # Success marker (CRITICAL - always visible)
    log_workflow_success("optimization", "Optuna",
                        trials=len(study.trials),
                        best_trial=study.best_trial.number if study.best_trial else -1,
                        best_value=study.best_value if study.best_trial else 0)
```

### 3.8 OptimizationRunner - Trial Execution (Silent)

**File**: `backtest/engine/optimization_runner.py`

```python
@classmethod
def run_trial(cls, trial_params, trial_id) -> OptimizationMetrics:
    """Run single optimization trial - SILENT unless error."""

    try:
        # Silent execution - no logging during optimization trials
        engine = EngineFactory.create_backtest_engine(
            config=config,
            indicators_dir=indicators_dir,
            strategy_logger_enabled=False,  # No CSV logging
        )

        # ... setup and run ...

        results = engine.run()
        return cls._extract_metrics(results)

    except Exception as e:
        # Only log errors (WARNING level - visible in optimization mode)
        error_msg = f"{type(e).__name__}: {e}"
        logger.warning(f"[OPTIMIZATION_RUNNER] Trial {trial_id} | ERROR | {error_msg}")
        return OptimizationMetrics.failed(error_msg)
```

---

## 4. Logging Utility Functions

### 4.1 Updated logging_utils.py

```python
"""
Quant Engine Logging Utilities
==============================

Context-aware logging for backtest and optimization workflows.

Modes:
- debug: Full visibility, all levels active
- best_trial: Key milestones, INFO and above
- optimization: Progress only, WARNING and above
"""

import logging
from typing import Literal, Optional

RunContext = Literal["optimization", "debug", "best_trial"]

# Module-level context for components to check
_current_context: RunContext = "debug"

def set_run_context(context: RunContext) -> None:
    """Set the current run context for all components."""
    global _current_context
    _current_context = context

def get_run_context() -> RunContext:
    """Get the current run context."""
    return _current_context

def should_log_details(context: Optional[RunContext] = None) -> bool:
    """Check if detailed logging should be enabled."""
    ctx = context or _current_context
    return ctx != "optimization"

def setup_backtest_logging(run_context: RunContext) -> None:
    """Configure logging based on execution context."""
    set_run_context(run_context)

    if run_context == "optimization":
        # Minimal logging - only progress and errors
        logging.getLogger().setLevel(logging.WARNING)

        # Suppress backtest component noise
        for logger_name in [
            "modules.quant_engine.backtest.engine.backtrader_strategy",
            "modules.quant_engine.backtest.engine.backtrader_engine",
            "modules.quant_engine.core.base.base_strategy",
            "modules.quant_engine.strategy.platform_agnostic",
        ]:
            logging.getLogger(logger_name).setLevel(logging.ERROR)

        # Keep optimization logging visible
        logging.getLogger("modules.quant_engine.backtest.optimization").setLevel(logging.WARNING)

    elif run_context == "debug":
        # Full visibility
        logging.getLogger().setLevel(logging.DEBUG)

        # All components at DEBUG
        for logger_name in [
            "modules.quant_engine",
        ]:
            logging.getLogger(logger_name).setLevel(logging.DEBUG)

    elif run_context == "best_trial":
        # Balanced - milestones visible
        logging.getLogger().setLevel(logging.INFO)

def log_workflow_start(context: RunContext, workflow: str, **kwargs) -> None:
    """Log workflow start - CRITICAL level for visibility."""
    logger = logging.getLogger("quant_engine")
    details = ", ".join(f"{k}={v}" for k, v in kwargs.items())
    logger.critical(f"[{context.upper()}] {workflow} | START | {details}")

def log_workflow_progress(context: RunContext, workflow: str,
                          completed: int, total: int, **kwargs) -> None:
    """Log workflow progress - WARNING level."""
    logger = logging.getLogger("quant_engine")
    pct = (completed / total) * 100 if total > 0 else 0
    details = ", ".join(f"{k}={v}" for k, v in kwargs.items())
    extra = f", {details}" if details else ""
    logger.warning(f"[{context.upper()}] {workflow} | PROGRESS | "
                  f"{completed}/{total} ({pct:.1f}%){extra}")

def log_workflow_success(context: RunContext, workflow: str, **metrics) -> None:
    """Log workflow success - CRITICAL level for visibility."""
    logger = logging.getLogger("quant_engine")
    details = ", ".join(f"{k}={v}" for k, v in metrics.items())
    logger.critical(f"[{context.upper()}] {workflow} | SUCCESS | {details}")

def log_workflow_failure(context: RunContext, workflow: str, error: str) -> None:
    """Log workflow failure - CRITICAL level for visibility."""
    logger = logging.getLogger("quant_engine")
    logger.critical(f"[{context.upper()}] {workflow} | FAILURE | {error}")

def log_result_summary(context: RunContext, workflow: str,
                       sharpe: float, total_return: float,
                       max_drawdown: float, num_trades: int) -> None:
    """Log comprehensive result summary - CRITICAL level."""
    logger = logging.getLogger("quant_engine")
    logger.critical(
        f"[{context.upper()}] {workflow} | RESULT | "
        f"Sharpe={sharpe:.3f}, Return={total_return:.2f}%, "
        f"MaxDD={max_drawdown:.2f}%, Trades={num_trades}"
    )

def log_zero_trades_warning(context: RunContext, workflow: str) -> None:
    """Log zero trades warning - WARNING level (always visible)."""
    logger = logging.getLogger("quant_engine")
    logger.warning(
        f"[{context.upper()}] {workflow} | WARNING | "
        "Zero trades executed! Check entry conditions, risk filters, and indicator values."
    )
```

---

## 5. Expected Output Examples

### 5.1 Debug Mode - Single Backtest (Full Visibility)

```
[DEBUG] Backtest | START | market=SHFE, instrument=aluminum, bars=5000
[DEBUG] DataLoad | INFO | rows=5000, range=2023-01-01 to 2024-12-31
[DEBUG] Engine | INFO | market_adapter=SHFEAdapter, frequency=intraday_15min, hooks=[SessionAwareHook]
[DEBUG] Execution | START | strategy=StrategyMain

# Bar-level decisions (DEBUG level)
[DEBUG] Risk | DECISION | can_trade=True, equity=100000, dd=0.00%, session_loss=0.00%
[DEBUG] Entry | DECISION | signal=HOLD, willr=-45, session=day_main, reason=not_oversold
[DEBUG] Risk | DECISION | can_trade=True, equity=100000, dd=0.00%, session_loss=0.00%
[DEBUG] Entry | DECISION | signal=LONG, willr=-85, session=day_main, strength=0.85, reason=oversold
[DEBUG] Sizer | DECISION | size=5, equity=100000, risk_per_contract=200, stop_dist=40
[DEBUG] Order | SUBMITTED | side=BUY, size=5, price=10500

# Position management
[DEBUG] Exit | DECISION | should_exit=False, close=10520, stop=10460, distance=60
[DEBUG] Exit | DECISION | should_exit=False, close=10550, stop=10510, distance=40
[DEBUG] Exit | DECISION | should_exit=True, close=10505, stop=10510, reason=stop_hit
[DEBUG] Order | SUBMITTED | side=SELL, size=5, price=10505

# Trade completion
[DEBUG] Trade | CLOSED | #1, pnl=25.00, status=WIN, bars_held=15

# Progress milestone
[DEBUG] Strategy | PROGRESS | bar=500, date=2023-03-15, position=0
[DEBUG] Strategy | PROGRESS | bar=1000, date=2023-05-20, position=5

# Final results
[DEBUG] Backtest | SUCCESS | trades=47, sharpe=1.25, return=23.5%
[DEBUG] Backtest | RESULT | Sharpe=1.250, Return=23.50%, MaxDD=-8.50%, Trades=47
```

### 5.2 Debug Mode - Zero Trades (Problem Detection)

```
[DEBUG] Backtest | START | market=SHFE, instrument=aluminum, bars=5000
[DEBUG] DataLoad | INFO | rows=5000, range=2023-01-01 to 2024-12-31
[DEBUG] Engine | INFO | market_adapter=SHFEAdapter, frequency=intraday_15min

# Bar-level shows WHY no trades
[DEBUG] Risk | BLOCKED | can_trade=False, equity=100000, dd=0.00%, reason=session_loss_limit
[DEBUG] Risk | BLOCKED | can_trade=False, equity=100000, dd=0.00%, reason=session_loss_limit
...
# OR
[DEBUG] Entry | DECISION | signal=HOLD, willr=-45, reason=not_oversold (threshold=-80)
[DEBUG] Entry | DECISION | signal=HOLD, willr=-50, reason=not_oversold (threshold=-80)
...
# OR
[DEBUG] Entry | DECISION | signal=HOLD, session=night_main, target_session=day_main, reason=wrong_session
...

# Final results with warning
[DEBUG] Backtest | WARNING | Zero trades executed! Check entry conditions and risk filters.
[DEBUG] Backtest | RESULT | Sharpe=0.000, Return=0.00%, MaxDD=0.00%, Trades=0
```

### 5.3 Optimization Mode (Progress Only)

```
[OPTIMIZATION] Optuna | START | trials=100, target=sharpe_ratio, workers=8

# Trial completions (WARNING level - visible)
[OPTIMIZATION] Trial | COMPLETE | #1, sharpe=0.85, trades=32
[OPTIMIZATION] Trial | COMPLETE | #2, sharpe=1.12, trades=45
[OPTIMIZATION] Trial | FAILED | #3, error=KeyError: 'invalid_indicator'
...

# Progress milestones (every 25 trials)
[OPTIMIZATION] Optuna | PROGRESS | 25/100 (25%), completed=23, failed=2, best_sharpe=1.34, ETA=6.5min
[OPTIMIZATION] Optuna | PROGRESS | 50/100 (50%), completed=47, failed=3, best_sharpe=1.45, ETA=4.2min
[OPTIMIZATION] Optuna | PROGRESS | 75/100 (75%), completed=71, failed=4, best_sharpe=1.52, ETA=2.1min
[OPTIMIZATION] Optuna | PROGRESS | 100/100 (100%), completed=95, failed=5, best_sharpe=1.52, ETA=0.0s

# Final result
[OPTIMIZATION] Optuna | SUCCESS | trials=100, best_trial=67, best_value=1.52
```

---

## 6. Debugger Agent Integration

### 6.1 Success Detection Patterns

```bash
# Check for successful completion
grep -q "\[DEBUG\] Backtest | SUCCESS" output.log && echo "SUCCESS"

# Check for zero trades (problem indicator)
grep -q "Zero trades executed" output.log && echo "ZERO_TRADES_PROBLEM"

# Extract result summary
grep "\[DEBUG\] Backtest | RESULT" output.log

# Check optimization success
grep -q "\[OPTIMIZATION\] Optuna | SUCCESS" output.log && echo "OPTUNA_SUCCESS"
```

### 6.2 Problem Detection Patterns

```bash
# Find blocked risk decisions
grep "\[DEBUG\] Risk | BLOCKED" output.log | head -5

# Find entry rejections
grep "\[DEBUG\] Entry | DECISION | signal=HOLD" output.log | head -5

# Find failed trials
grep "\[OPTIMIZATION\] Trial | FAILED" output.log

# Find errors
grep "ERROR" output.log
```

### 6.3 Diagnostic Commands for Debugger Agent

```bash
# If zero trades: Check entry conditions
grep "Entry | DECISION" output.log | grep "signal=HOLD" | head -10
# Look for: reason=not_oversold, reason=wrong_session, etc.

# If zero trades: Check risk blocks
grep "Risk | BLOCKED" output.log | head -10
# Look for: reason=drawdown_limit, reason=session_loss_limit

# If optimization fails: Check trial errors
grep "Trial | FAILED" output.log
# Look for: KeyError, AttributeError, TypeError

# Count trade attempts vs completions
echo "Entry signals: $(grep 'Entry | DECISION | signal=LONG' output.log | wc -l)"
echo "Orders submitted: $(grep 'Order | SUBMITTED' output.log | wc -l)"
echo "Trades closed: $(grep 'Trade | CLOSED' output.log | wc -l)"
```

---

## 7. Implementation Priority

### Phase 1: Critical Markers (Immediate)
1. Add SUCCESS/FAILURE markers to BacktestRunner
2. Add zero trades warning
3. Add RESULT summary logging
4. Update logging_utils.py with context management

### Phase 2: Decision Logging (High Priority)
1. Add entry decision logging to base_strategy.py
2. Add exit decision logging
3. Add risk decision logging
4. Add sizer decision logging

### Phase 3: Optimization Logging (Medium Priority)
1. Add trial completion logging to optuna_study.py
2. Add progress milestone logging
3. Suppress backtest noise in optimization mode

### Phase 4: Polish (Low Priority)
1. Add bar progress logging (every N bars)
2. Add trade completion logging
3. Add order submission logging

---

## 8. Configuration

### Environment Variables

```bash
# Override log level
export QUANT_ENGINE_LOG_LEVEL=DEBUG

# Enable bar-by-bar logging (very verbose)
export QUANT_ENGINE_BAR_LOGGING=1

# Set progress interval for optimization
export QUANT_ENGINE_OPTUNA_PROGRESS_INTERVAL=25
```

### Runtime Configuration

```python
from modules.quant_engine.logging_utils import setup_backtest_logging

# Set mode before running
setup_backtest_logging("debug")      # Full visibility
setup_backtest_logging("optimization")  # Progress only
setup_backtest_logging("best_trial")    # Balanced
```

---

## Summary

This logging architecture provides:

1. **Clear SUCCESS/FAILURE markers** for automated detection by debugger_agent
2. **Component decision logging** to understand WHY trades are/aren't executed
3. **Zero trades warning** with diagnostic hints
4. **Context-aware verbosity** - detailed in debug, silent in optimization
5. **Structured format** for easy grep/parsing
6. **Progress tracking** for long-running operations

The key insight is that the debugger_agent needs to understand not just WHAT happened (0 trades) but WHY it happened (entry conditions not met, risk blocked, etc.). This design provides that visibility.
