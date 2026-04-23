"""Phase A9 — every bundled strategy_indicator_list.json must round-trip through IndicatorList.

Walks echolon/native/templates/ + echolon/examples/ and validates each
strategy_indicator_list.json against the catalog-aware schema. Catches drift
between shipped fixtures and the catalog.
"""
import json
from pathlib import Path

import pytest

from echolon.indicators.schema import IndicatorList

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _all_fixture_paths():
    roots = [
        _REPO_ROOT / "echolon" / "native" / "templates",
        _REPO_ROOT / "examples",
    ]
    paths = []
    for r in roots:
        if r.exists():
            paths.extend(r.rglob("strategy_indicator_list.json"))
    return paths


_FIXTURES = _all_fixture_paths()


@pytest.mark.parametrize("fixture_path", _FIXTURES, ids=lambda p: str(p.relative_to(_REPO_ROOT)))
def test_fixture_validates_against_indicator_list_schema(fixture_path):
    data = json.loads(fixture_path.read_text())
    # Must be flat-dict (no 4-section section-key literals).
    for legacy_key in (
        "indicators_with_lookback",
        "indicators_without_lookback",
        "indicators_with_special_params",
        "system_provided_indicators",
    ):
        assert legacy_key not in data, (
            f"{fixture_path}: still contains legacy 4-section key {legacy_key!r}; "
            f"migrate to flat-dict (see docs/superpowers/plans/2026-04-22-indicator-validation-hardening.md)"
        )
    # Must validate through the catalog-aware schema.
    IndicatorList.model_validate(data)


def test_at_least_one_fixture_is_collected():
    """Guard: if the walker returns nothing, the parameterized test silently passes."""
    assert len(_FIXTURES) >= 3, f"Expected >= 3 fixtures, collected {len(_FIXTURES)}: {_FIXTURES}"
