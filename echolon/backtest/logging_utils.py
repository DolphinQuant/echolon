"""
Backtest Module Logging Utilities
=================================

Centralized logging configuration and utilities for consistent, context-aware
terminal output across the backtest module.

This module provides:
- Context-aware logging setup (optimization/debug/best_trial)
- Structured log format helpers
- Workflow lifecycle logging (start/progress/success/failure)
- Component decision logging for strategy debugging

Logging Modes:
- optimization: Minimal logging (WARNING+) - only progress and errors
- debug: Full visibility (DEBUG+) - bar-by-bar decisions visible
- best_trial: Balanced logging (INFO+) - milestones and results

Message Format:
    [CONTEXT] Component | STATUS | key1=value1, key2=value2
"""

import logging
from typing import Literal, Optional, Dict, Any

# Type for execution contexts
RunContext = Literal["optimization", "debug", "best_trial"]

# Module-level context for components to check
_current_context: RunContext = "debug"


def set_run_context(context: RunContext) -> None:
    """
    Set the current run context for all components.

    This should be called at the start of any backtest/optimization run.
    Components can then check the context to determine logging verbosity.

    Args:
        context: The execution context
    """
    global _current_context
    _current_context = context


def get_run_context() -> RunContext:
    """
    Get the current run context.

    Returns:
        Current execution context
    """
    return _current_context


def setup_backtest_logging(run_context: RunContext) -> None:
    """
    Configure logging for backtest module based on execution context.

    This function sets up appropriate log levels for different execution modes:
    - optimization: Minimal logging (WARNING+) for high-throughput runs
    - debug: Full visibility (INFO+) for development and debugging
    - best_trial: Balanced logging (INFO+) for production runs

    Args:
        run_context: Execution mode controlling log verbosity
    """
    # Set module-level context for components to check
    set_run_context(run_context)

    if run_context == "optimization":
        # Minimal logging for high-throughput optimization
        root_logger = logging.getLogger()
        root_logger.setLevel(logging.WARNING)

        # Allow ERROR and CRITICAL for all backtest components
        # (important for debugging failed trials)
        for logger_name in [
            "backtest",
            "backtesting",
            "backtesting.engine",
            "backtesting.engine.backtest_engine",
            "backtesting.engine.analyzers",
            "backtesting.engine.enhanced_position",
            "backtrader_strategy",
            "backtrader_strategy.core",
            "prepare_data",
            # quant_engine module loggers (suppress detailed bar-by-bar logs)
            "modules.quant_engine",
            "modules.quant_engine.backtest",
            "modules.quant_engine.backtest.engine",
            "modules.quant_engine.backtest.engine.backtrader_strategy",
            "modules.quant_engine.backtest.engine.hooks",
            "modules.quant_engine.core",
            "modules.quant_engine.core.base",
            "modules.quant_engine.core.base.base_component",
            "modules.quant_engine.core.base.base_strategy",
            "modules.quant_engine.data_loader",
        ]:
            logging.getLogger(logger_name).setLevel(logging.ERROR)

        # Suppress backtrader's internal logging
        logging.getLogger("backtrader").setLevel(logging.ERROR)
        logging.getLogger("backtrader.broker").setLevel(logging.ERROR)
        logging.getLogger("backtrader.cerebro").setLevel(logging.ERROR)

        # Suppress third-party verbose loggers
        logging.getLogger("matplotlib").setLevel(logging.ERROR)

    elif run_context == "debug":
        # Full visibility for development
        root_logger = logging.getLogger()
        root_logger.setLevel(logging.DEBUG)

        # All backtest components at INFO level
        for logger_name in ["backtest", "backtesting", "backtrader_strategy", "prepare_data"]:
            logging.getLogger(logger_name).setLevel(logging.INFO)

        # Suppress matplotlib in debug too
        logging.getLogger("matplotlib").setLevel(logging.WARNING)

    elif run_context == "best_trial":
        # Balanced logging for production runs
        root_logger = logging.getLogger()
        root_logger.setLevel(logging.INFO)

        # Backtest components at INFO
        logging.getLogger("backtest").setLevel(logging.INFO)
        logging.getLogger("backtesting").setLevel(logging.INFO)
        logging.getLogger("backtrader_strategy").setLevel(logging.INFO)

        # Suppress noisy sub-components
        logging.getLogger("backtesting.engine.analyzers").setLevel(logging.WARNING)
        logging.getLogger("modules.quant_engine.backtest.engine.hooks.contract_aware.broker").setLevel(logging.WARNING)

        # Suppress matplotlib
        logging.getLogger("matplotlib").setLevel(logging.ERROR)


def get_logger(name: str) -> logging.Logger:
    """
    Get a logger for a specific module.

    Args:
        name: Module name (usually __name__)

    Returns:
        Logger instance
    """
    return logging.getLogger(name)


def log_workflow_start(context: RunContext, workflow: str, **kwargs) -> None:
    """
    Log workflow start with consistent format.

    Format: "[CONTEXT] Workflow | START | key1=value1, key2=value2"

    Args:
        context: Execution context (optimization/debug/best_trial)
        workflow: Workflow name (e.g., "Backtest", "DataPrep::Indicators")
        **kwargs: Additional details to log (key=value pairs)
    """
    logger = logging.getLogger("backtest")
    details = ", ".join(f"{k}={v}" for k, v in kwargs.items())
    msg = f"[{context.upper()}] {workflow} | START"
    if details:
        msg += f" | {details}"
    logger.warning(msg)


def log_workflow_progress(
    context: RunContext,
    workflow: str,
    completed: int,
    total: int,
    extra: Optional[str] = None
) -> None:
    """
    Log workflow progress with percentage and optional extra info.

    Format: "[CONTEXT] Workflow | PROGRESS | 50/100 (50.0%)[, extra]"

    Args:
        context: Execution context
        workflow: Workflow name
        completed: Number of completed items
        total: Total number of items
        extra: Optional extra information (e.g., "ETA: 5min")
    """
    logger = logging.getLogger("backtest")
    pct = (completed / total) * 100 if total > 0 else 0
    msg = f"[{context.upper()}] {workflow} | PROGRESS | {completed}/{total} ({pct:.1f}%)"
    if extra:
        msg += f", {extra}"
    logger.warning(msg)


def log_workflow_success(context: RunContext, workflow: str, **metrics) -> None:
    """
    Log workflow success with metrics.

    Format: "[CONTEXT] Workflow | SUCCESS | metric1=value1, metric2=value2"

    Args:
        context: Execution context
        workflow: Workflow name
        **metrics: Success metrics to log (key=value pairs)
    """
    logger = logging.getLogger("backtest")
    details = ", ".join(f"{k}={v}" for k, v in metrics.items())
    msg = f"[{context.upper()}] {workflow} | SUCCESS"
    if details:
        msg += f" | {details}"
    logger.critical(msg)


def log_workflow_failure(context: RunContext, workflow: str, error: str) -> None:
    """
    Log workflow failure with error message.

    Format: "[CONTEXT] Workflow | FAILURE | error description"

    Args:
        context: Execution context
        workflow: Workflow name
        error: Error description
    """
    logger = logging.getLogger("backtest")
    logger.critical(f"[{context.upper()}] {workflow} | FAILURE | {error}")


def log_workflow_info(context: RunContext, workflow: str, message: str) -> None:
    """
    Log informational message for workflow.

    Format: "[CONTEXT] Workflow | INFO | message"

    Args:
        context: Execution context
        workflow: Workflow name
        message: Information message
    """
    logger = logging.getLogger("backtest")
    logger.info(f"[{context.upper()}] {workflow} | INFO | {message}")


def log_result_summary(
    context: RunContext,
    workflow: str,
    sharpe: float,
    total_return: float,
    max_drawdown: float,
    num_trades: int,
    **extra_metrics
) -> None:
    """
    Log comprehensive result summary for backtest runs.

    This creates a CRITICAL level log that's always visible and easily parseable
    by automated tools (e.g., debugger_agent.py).

    Format: "[CONTEXT] Workflow | RESULT SUMMARY | Sharpe: X.XXX | Return: X.XX% | ..."

    Args:
        context: Execution context
        workflow: Workflow name
        sharpe: Sharpe ratio
        total_return: Total return percentage
        max_drawdown: Maximum drawdown percentage
        num_trades: Number of trades
        **extra_metrics: Additional metrics (e.g., win_rate=55.2)
    """
    logger = logging.getLogger("backtest")

    # Format core metrics
    core_metrics = (
        f"Sharpe: {sharpe:.3f} | "
        f"Total Return: {total_return:.2f}% | "
        f"Max DD: {max_drawdown:.2f}% | "
        f"Trades: {num_trades}"
    )

    # Add extra metrics if provided
    if extra_metrics:
        extra = " | ".join(f"{k.replace('_', ' ').title()}: {v:.2f}" if isinstance(v, float)
                          else f"{k.replace('_', ' ').title()}: {v}"
                          for k, v in extra_metrics.items())
        core_metrics += f" | {extra}"

    logger.critical(f"[{context.upper()}] {workflow} | RESULT SUMMARY | {core_metrics}")


def log_zero_trades_warning(
    context: RunContext,
    workflow: str,
    bars_processed: int,
    entry_signals_generated: int = 0,
    entry_signals_blocked: int = 0,
    risk_blocks: int = 0,
) -> None:
    """
    Log warning when backtest produces zero trades with diagnostic info.

    This creates a WARNING level log that helps debugger_agent identify
    why no trades were executed (signal generation vs risk blocking).

    Format: "[CONTEXT] Workflow | ZERO TRADES | bars=N, signals=N, blocked=N, risk_blocks=N"

    Args:
        context: Execution context
        workflow: Workflow name
        bars_processed: Total bars processed
        entry_signals_generated: Number of entry signals generated
        entry_signals_blocked: Number of signals blocked by filters
        risk_blocks: Number of signals blocked by risk manager
    """
    logger = logging.getLogger("backtest")

    diagnostics = (
        f"bars={bars_processed}, "
        f"entry_signals={entry_signals_generated}, "
        f"signals_blocked={entry_signals_blocked}, "
        f"risk_blocks={risk_blocks}"
    )

    # Provide diagnostic guidance
    if entry_signals_generated == 0:
        hint = "HINT: No entry signals generated - check entry conditions"
    elif entry_signals_blocked + risk_blocks >= entry_signals_generated:
        hint = "HINT: All signals blocked - check filter/risk thresholds"
    else:
        hint = "HINT: Signals generated but not executed - check order logic"

    logger.warning(
        f"[{context.upper()}] {workflow} | ZERO TRADES WARNING | {diagnostics} | {hint}"
    )


def should_log_details(run_context: RunContext) -> bool:
    """
    Determine if detailed logging should be enabled based on context.

    Use this to conditionally log verbose information:
    - optimization: False (suppress details)
    - debug: True (show all details)
    - best_trial: True (show details for production runs)

    Args:
        run_context: Execution context

    Returns:
        True if details should be logged
    """
    return run_context != "optimization"


def format_time_seconds(seconds: float) -> str:
    """
    Format seconds into human-readable string.

    Args:
        seconds: Time in seconds

    Returns:
        Formatted string (e.g., "4.2s", "1.5m", "2.3h")
    """
    if seconds < 60:
        return f"{seconds:.1f}s"
    elif seconds < 3600:
        return f"{seconds/60:.1f}m"
    else:
        return f"{seconds/3600:.1f}h"


def format_eta(remaining: int, rate: float) -> str:
    """
    Calculate and format ETA string.

    Args:
        remaining: Number of items remaining
        rate: Processing rate (items per second)

    Returns:
        Formatted ETA string (e.g., "ETA: 5.2m", "ETA: N/A")
    """
    if rate <= 0:
        return "ETA: N/A"

    eta_seconds = remaining / rate
    return f"ETA: {format_time_seconds(eta_seconds)}"
