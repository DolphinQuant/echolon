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
