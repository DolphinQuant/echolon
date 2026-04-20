"""Extractor capabilities declaration tests.

Task 7 implementation: Replace hasattr() duck-typing with explicit
capabilities: ClassVar[Set[str]] per extractor.
"""
import pytest


def test_all_extractors_declare_capabilities():
    """All extractors must declare a capabilities set."""
    from echolon.data.extractors.shfe.day_extractor import SHFEDayExtractor
    from echolon.data.extractors.shfe.minute_extractor import SHFEMinuteExtractor
    from echolon.data.extractors.shfe.live_day_extractor import SHFELiveDayExtractor
    from echolon.data.extractors.binance.perpetual_extractor import BinancePerpetualExtractor

    for cls in (
        SHFEDayExtractor,
        SHFEMinuteExtractor,
        SHFELiveDayExtractor,
        BinancePerpetualExtractor,
    ):
        assert hasattr(cls, "capabilities"), f"{cls.__name__} missing capabilities attribute"
        assert isinstance(cls.capabilities, set), f"{cls.__name__}.capabilities must be a set"
        assert "batch" in cls.capabilities, f"{cls.__name__} must declare 'batch' capability"


def test_shfe_day_extractor_capabilities():
    """SHFEDayExtractor: {batch, calendar_generate}."""
    from echolon.data.extractors.shfe.day_extractor import SHFEDayExtractor

    assert SHFEDayExtractor.capabilities == {"batch", "calendar_generate"}


def test_shfe_minute_extractor_capabilities():
    """SHFEMinuteExtractor: {batch, calendar_generate, main_contract}."""
    from echolon.data.extractors.shfe.minute_extractor import SHFEMinuteExtractor

    assert SHFEMinuteExtractor.capabilities == {
        "batch",
        "calendar_generate",
        "main_contract",
    }


def test_shfe_live_day_extractor_capabilities():
    """SHFELiveDayExtractor: {batch, incremental, calendar_load, main_contract}."""
    from echolon.data.extractors.shfe.live_day_extractor import SHFELiveDayExtractor

    assert SHFELiveDayExtractor.capabilities == {
        "batch",
        "incremental",
        "calendar_load",
        "main_contract",
    }


def test_binance_perpetual_extractor_capabilities():
    """BinancePerpetualExtractor: {batch, calendar_generate}."""
    from echolon.data.extractors.binance.perpetual_extractor import BinancePerpetualExtractor

    assert BinancePerpetualExtractor.capabilities == {"batch", "calendar_generate"}


def test_live_extractor_has_incremental():
    """Only the live extractor should have 'incremental' capability."""
    from echolon.data.extractors.shfe.live_day_extractor import SHFELiveDayExtractor
    from echolon.data.extractors.shfe.day_extractor import SHFEDayExtractor
    from echolon.data.extractors.shfe.minute_extractor import SHFEMinuteExtractor

    assert "incremental" in SHFELiveDayExtractor.capabilities
    assert "incremental" not in SHFEDayExtractor.capabilities
    assert "incremental" not in SHFEMinuteExtractor.capabilities


def test_minute_and_live_have_main_contract():
    """Minute and live extractors should have 'main_contract' capability."""
    from echolon.data.extractors.shfe.minute_extractor import SHFEMinuteExtractor
    from echolon.data.extractors.shfe.live_day_extractor import SHFELiveDayExtractor
    from echolon.data.extractors.shfe.day_extractor import SHFEDayExtractor

    assert "main_contract" in SHFEMinuteExtractor.capabilities
    assert "main_contract" in SHFELiveDayExtractor.capabilities
    assert "main_contract" not in SHFEDayExtractor.capabilities


def test_calendar_load_vs_generate():
    """Live extractor has 'calendar_load'; others have 'calendar_generate'."""
    from echolon.data.extractors.shfe.day_extractor import SHFEDayExtractor
    from echolon.data.extractors.shfe.minute_extractor import SHFEMinuteExtractor
    from echolon.data.extractors.shfe.live_day_extractor import SHFELiveDayExtractor
    from echolon.data.extractors.binance.perpetual_extractor import BinancePerpetualExtractor

    # Live loads a pre-built calendar
    assert "calendar_load" in SHFELiveDayExtractor.capabilities
    assert "calendar_generate" not in SHFELiveDayExtractor.capabilities

    # Others generate from data
    assert "calendar_generate" in SHFEDayExtractor.capabilities
    assert "calendar_load" not in SHFEDayExtractor.capabilities

    assert "calendar_generate" in SHFEMinuteExtractor.capabilities
    assert "calendar_load" not in SHFEMinuteExtractor.capabilities

    assert "calendar_generate" in BinancePerpetualExtractor.capabilities
    assert "calendar_load" not in BinancePerpetualExtractor.capabilities
