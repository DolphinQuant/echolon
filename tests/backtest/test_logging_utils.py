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


import asyncio


def test_run_context_isolated_across_asyncio_tasks():
    """Parallel trials (asyncio or concurrent.futures) must not share run_context."""
    results = {}

    async def setter_a():
        logging_utils.set_run_context("optimization")
        await asyncio.sleep(0.01)
        results["a"] = logging_utils.get_run_context()

    async def setter_b():
        logging_utils.set_run_context("debug")
        await asyncio.sleep(0.01)
        results["b"] = logging_utils.get_run_context()

    async def runner():
        await asyncio.gather(setter_a(), setter_b())

    asyncio.run(runner())
    assert results["a"] == "optimization"
    assert results["b"] == "debug"
