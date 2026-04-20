"""Extractors raise when neither output_dir nor a default-paths override is supplied."""
import pytest

from echolon.data.extractors.shfe.file_day_extractor import SHFEFileDayExtractor
from echolon.data.extractors.shfe.api_minute_extractor import SHFEApiMinuteExtractor
from echolon.data.extractors.shfe.api_day_extractor import SHFEApiDayExtractor


def test_file_day_extractor_requires_output_dir(tmp_path):
    ex = SHFEFileDayExtractor(market="SHFE", asset="aluminum")
    # extract_raw without any path-providing args must raise
    with pytest.raises(ValueError, match="output_dir"):
        ex.extract_raw()   # no input/output dirs


def test_api_minute_extractor_requires_output_dir():
    ex = SHFEApiMinuteExtractor(market="SHFE", asset="aluminum")
    with pytest.raises(ValueError, match="output_dir"):
        ex.extract_raw()


def test_api_day_extractor_requires_output_dir():
    ex = SHFEApiDayExtractor(market="SHFE", asset="aluminum")
    with pytest.raises(ValueError, match="output_dir"):
        ex.extract_raw()


def test_no_project_root_write_in_extractor_source():
    """Static assertion — grep the sources for PROJECT_ROOT / 'data' writes."""
    import importlib.util
    from pathlib import Path
    # Locate the extractors directory via the base module's file
    spec = importlib.util.find_spec("echolon.data.extractors.base")
    base = Path(spec.origin).parent  # echolon/data/extractors/
    for py in base.rglob("*.py"):
        src = py.read_text()
        # Allow imports of PROJECT_ROOT (for reading config), forbid joining into 'data' dir
        assert 'PROJECT_ROOT / "data"' not in src and "PROJECT_ROOT, 'data'" not in src, \
            f"install-dir write in {py}"
