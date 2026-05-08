"""Unit tests for DailyScheduler (extracted from PortfolioTradingRunner
in 2026-05-08 R2 refactor)."""
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import pytz

from echolon.live.config.portfolio_deploy_config import (
    SlotConfig, SlotDashboardConfig, DeploySettings,
)


def _make_config(tmp_path):
    sc = SlotConfig(
        slot_id="al_s1", strategy_id="al_test", cluster="al", version="1.0",
        instrument="aluminum", instrument_code="al", market="SHFE",
        frequency="interday", bar_size="1d", initial_capital=100000.0,
        strategy_code_dir=str(tmp_path / "strategy"), trial_params_path="",
        enabled=True, dashboard=SlotDashboardConfig(),
    )
    from echolon.live.config.portfolio_deploy_config import (
        PortfolioDeployConfig, AccountConfig,
    )
    cfg = PortfolioDeployConfig()
    cfg.slots = [sc]
    cfg.deploy = DeploySettings(
        trading_calendar_path=str(tmp_path / "cal.csv"),
        night_market_schedule_hour=20, night_market_schedule_minute=30,
        day_only_schedule_hour=14, day_only_schedule_minute=45,
        misfire_grace_time=3600,
    )
    cfg.account = AccountConfig()
    return cfg, sc


def test_daily_scheduler_invokes_cycle_callback_on_trading_day(tmp_path):
    """When the scheduled job fires on a trading day, the on_cycle_trigger
    callback runs and on_present_date_set is invoked first."""
    from echolon.live.orchestrator.scheduler import DailyScheduler

    cfg, sc = _make_config(tmp_path)
    sched = DailyScheduler(
        config=cfg, slots=[sc], market_data_dir=tmp_path / "data",
        portfolio_dir=str(tmp_path / "portfolio"),
        timezone=pytz.timezone("Asia/Shanghai"),
        log=MagicMock(),
    )

    # Inject a no-op _ensure_trading_calendars to avoid SHFE extractor work.
    sched._ensure_trading_calendars = lambda: None

    cycle_calls = []
    present_dates = []

    with patch("echolon.live.orchestrator.scheduler.is_trading_day", return_value=True), \
         patch.object(sched, "_reschedule_next_job"):
        # Wire up callbacks
        sched._on_cycle_trigger = lambda: cycle_calls.append(True)
        sched._on_present_date_set = lambda dt: present_dates.append(dt)
        sched._is_running = lambda: True

        # Directly invoke the internal handler — bypasses APScheduler timing.
        sched._market_open_job()

    assert len(cycle_calls) == 1
    assert len(present_dates) == 1
    assert isinstance(present_dates[0], datetime)


def test_daily_scheduler_skips_callback_on_non_trading_day(tmp_path):
    """When the scheduled job fires on a non-trading day, the on_cycle_trigger
    is NOT invoked but reschedule still runs."""
    from echolon.live.orchestrator.scheduler import DailyScheduler

    cfg, sc = _make_config(tmp_path)
    sched = DailyScheduler(
        config=cfg, slots=[sc], market_data_dir=tmp_path / "data",
        portfolio_dir=str(tmp_path / "portfolio"),
        timezone=pytz.timezone("Asia/Shanghai"),
        log=MagicMock(),
    )
    sched._ensure_trading_calendars = lambda: None

    cycle_calls = []

    with patch("echolon.live.orchestrator.scheduler.is_trading_day", return_value=False), \
         patch.object(sched, "_reschedule_next_job") as mock_reschedule:
        sched._on_cycle_trigger = lambda: cycle_calls.append(True)
        sched._on_present_date_set = lambda dt: None
        sched._is_running = lambda: True

        sched._market_open_job()

    assert len(cycle_calls) == 0
    mock_reschedule.assert_called_once()


def test_daily_scheduler_writes_heartbeat_with_expected_fields(tmp_path):
    """write_heartbeat writes the canonical 5-field content to
    portfolio_dir/scheduler_heartbeat.txt."""
    from echolon.live.orchestrator.scheduler import DailyScheduler

    cfg, sc = _make_config(tmp_path)
    portfolio_dir = tmp_path / "portfolio"
    portfolio_dir.mkdir()
    sched = DailyScheduler(
        config=cfg, slots=[sc], market_data_dir=tmp_path / "data",
        portfolio_dir=str(portfolio_dir),
        timezone=pytz.timezone("Asia/Shanghai"),
        log=MagicMock(),
    )

    # Stub the scheduler — just need get_jobs() to return [].
    sched._scheduler = MagicMock()
    sched._scheduler.get_jobs.return_value = []
    sched._is_running = lambda: True
    sched._slot_count = lambda: 3
    sched._order_router_tripped = lambda: False

    sched.write_heartbeat()

    heartbeat = portfolio_dir / "scheduler_heartbeat.txt"
    assert heartbeat.exists()
    content = heartbeat.read_text(encoding="utf-8")
    assert "now=" in content
    assert "next_daily_job=NONE" in content
    assert "running=True" in content
    assert "slots=3" in content
    assert "order_router_tripped=False" in content


def test_daily_scheduler_skips_when_runner_not_running(tmp_path):
    """Shutdown-race guard: when the trigger fires after runner.running
    has been set False, _market_open_job MUST return without invoking
    the cycle callback or the reschedule path."""
    from echolon.live.orchestrator.scheduler import DailyScheduler

    cfg, sc = _make_config(tmp_path)
    sched = DailyScheduler(
        config=cfg, slots=[sc], market_data_dir=tmp_path / "data",
        portfolio_dir=str(tmp_path / "portfolio"),
        timezone=pytz.timezone("Asia/Shanghai"),
        log=MagicMock(),
    )
    sched._ensure_trading_calendars = lambda: None

    cycle_calls = []

    with patch("echolon.live.orchestrator.scheduler.is_trading_day", return_value=True), \
         patch.object(sched, "_reschedule_next_job") as mock_reschedule:
        sched._on_cycle_trigger = lambda: cycle_calls.append(True)
        sched._on_present_date_set = lambda dt: None
        sched._is_running = lambda: False  # simulate shutdown in progress

        sched._market_open_job()

    # Cycle MUST NOT fire when not running.
    assert len(cycle_calls) == 0
    # Reschedule MUST NOT fire either — the runner is shutting down,
    # so re-arming the scheduler is wrong.
    mock_reschedule.assert_not_called()
