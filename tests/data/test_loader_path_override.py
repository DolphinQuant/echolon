"""Loaders accept an explicit path override, bypassing MARKET_DATA_DIR convention."""
import pandas as pd
import pytest

from echolon.data.loaders.ohlcv_loader import load_ohlcv, load_contract_ohlcv
from echolon.data.loaders.calendar_loader import load_trading_calendar, get_trading_dates
from echolon.data.loaders.session_availability_loader import SessionAvailabilityLoader


# ---------------------------------------------------------------------------
# ohlcv_loader
# ---------------------------------------------------------------------------

def test_load_ohlcv_accepts_path_override(tmp_path):
    custom = tmp_path / "custom_ohlcv.csv"
    custom.write_text(
        "date,open,high,low,close,volume\n"
        "2020-01-02,100,101,99,100.5,1000\n"
        "2020-01-03,101,102,100,101.5,1100\n"
    )
    df = load_ohlcv(market="SHFE", asset="aluminum", path=str(custom))
    assert len(df) == 2
    assert list(df.columns) == ["date", "open", "high", "low", "close", "volume"]


def test_load_ohlcv_path_override_missing_file_raises(tmp_path):
    from echolon.errors import DataError

    with pytest.raises(DataError) as exc:
        load_ohlcv(market="SHFE", asset="aluminum", path=str(tmp_path / "does_not_exist.csv"))
    assert exc.value.code == "DAT-001"


def test_load_ohlcv_path_override_bypasses_market_data_dir(tmp_path):
    """When path is given, MARKET_DATA_DIR/{market}/{asset}/sort_by_date.csv is NOT used."""
    custom = tmp_path / "override.csv"
    custom.write_text("date,open,high,low,close,volume\n2020-01-02,5,6,4,5.5,999\n")
    # This would fail if the loader tried to build the default path (no such dir)
    df = load_ohlcv(market="NONEXISTENT_MARKET", asset="nonexistent_asset", path=str(custom))
    assert len(df) == 1


def test_load_contract_ohlcv_accepts_path_override(tmp_path):
    custom = tmp_path / "al2403.csv"
    custom.write_text(
        "date,open,high,low,close,volume\n"
        "2024-03-01,100,101,99,100.5,500\n"
    )
    df = load_contract_ohlcv(market="SHFE", asset="aluminum", contract="al2403",
                              path=str(custom))
    assert df is not None
    assert len(df) == 1


def test_load_contract_ohlcv_path_override_missing_returns_none(tmp_path):
    """load_contract_ohlcv returns None (not raises) for missing contract — keep that behaviour."""
    result = load_contract_ohlcv(
        market="SHFE", asset="aluminum", contract="al9999",
        path=str(tmp_path / "does_not_exist.csv")
    )
    assert result is None


# ---------------------------------------------------------------------------
# calendar_loader
# ---------------------------------------------------------------------------

def test_load_trading_calendar_accepts_path_override(tmp_path):
    custom = tmp_path / "cal.csv"
    custom.write_text("date,is_trading_day\n2020-01-02,1\n2020-01-03,1\n")
    df = load_trading_calendar(market="SHFE", asset="aluminum", path=str(custom))
    assert len(df) == 2


def test_load_trading_calendar_path_override_bypasses_market_data_dir(tmp_path):
    custom = tmp_path / "cal.csv"
    custom.write_text("date,is_trading_day\n2020-01-02,1\n")
    df = load_trading_calendar(market="NONEXISTENT", asset="nobody", path=str(custom))
    assert len(df) == 1


def test_load_trading_calendar_path_override_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_trading_calendar(market="SHFE", asset="aluminum",
                              path=str(tmp_path / "missing.csv"))


def test_get_trading_dates_accepts_path_override(tmp_path):
    custom = tmp_path / "cal.csv"
    custom.write_text("date,is_trading_day\n2020-01-02,1\n2020-01-06,1\n")
    dates = get_trading_dates(market="SHFE", asset="aluminum", path=str(custom))
    assert len(dates) == 2


# ---------------------------------------------------------------------------
# session_availability_loader
# ---------------------------------------------------------------------------

def test_session_availability_loader_accepts_path_override(tmp_path):
    csv = tmp_path / "session_availability.csv"
    csv.write_text(
        "trading_date,has_night,has_morning,has_afternoon,"
        "night_bars,morning_bars,afternoon_bars,total_bars\n"
        "20200102,1,1,1,60,120,60,240\n"
        "20200103,0,1,1,0,120,60,180\n"
    )
    loader = SessionAvailabilityLoader(
        market="SHFE",
        instrument="aluminum",
        bar_size_minutes=1,
        path=str(csv),
    )
    assert loader.is_loaded
    assert loader.has_night_session("20200102") is True
    assert loader.has_night_session("20200103") is False


def test_session_availability_loader_path_override_missing_file(tmp_path):
    """When path is given but missing, loader should warn but not crash (graceful)."""
    loader = SessionAvailabilityLoader(
        market="SHFE",
        instrument="aluminum",
        bar_size_minutes=1,
        path=str(tmp_path / "does_not_exist.csv"),
    )
    # Missing file → _loaded stays False (same behaviour as missing default path)
    assert not loader.is_loaded


def test_session_availability_loader_path_override_bypasses_market_data_dir(tmp_path):
    """With path override, a non-existent market/instrument is accepted."""
    csv = tmp_path / "sa.csv"
    csv.write_text(
        "trading_date,has_night_session,has_day_session,"
        "night_session_bars,day_session_bars,total_bars\n"
        "20200102,1,1,120,180,300\n"
    )
    loader = SessionAvailabilityLoader(
        market="FAKE_MARKET",
        instrument="fake_instrument",
        bar_size_minutes=15,
        bar_size="15m",
        path=str(csv),
    )
    assert loader.is_loaded
