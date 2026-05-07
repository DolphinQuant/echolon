"""Phase A7 — deploy orchestrators call run_indicator_calculation with the real signature.

No unit tests existed previously; the old kwargs (indicator_config=, selected_only=,
mode=, optimize_regime=) would have raised TypeError at runtime. These tests
assert the call shape symbolically by grep'ing the source.
"""
import inspect
from pathlib import Path

from echolon.indicators.run import run_indicator_calculation


def _src(mod_path: str) -> str:
    return Path(mod_path).read_text(encoding="utf-8")


def test_run_indicator_calculation_signature_has_indicator_list():
    """The signature we rely on. Reject surprise renames."""
    sig = inspect.signature(run_indicator_calculation)
    assert "indicator_list" in sig.parameters
    assert "ctx" in sig.parameters
    assert "output_dir" in sig.parameters


def test_portfolio_does_not_use_deprecated_kwargs():
    src = _src("echolon/live/orchestrator/portfolio.py")
    # These kwargs do NOT exist on run_indicator_calculation — must not appear as kwargs.
    for bad in ("selected_only=", "mode=", "optimize_regime=", "indicator_config="):
        assert bad not in src, f"portfolio.py still references deprecated kwarg {bad!r}"
    # Must pass the actual kwarg (portfolio uses merged_indicator_list from the grouping step)
    assert "indicator_list=merged_indicator_list" in src
