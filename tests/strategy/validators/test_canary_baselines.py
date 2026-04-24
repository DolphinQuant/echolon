"""Binding FP guardrail (Part B1, validation principle 7).

Two baseline sources, one guardrail:

- ``LEGACY_BASELINES`` — archived strategies under
  strategy_mining/DolphinQuantStrategy_al1/output/<version>/code/.
  These use pre-v0.3 relative imports (``from ...core.*``) that no
  longer resolve under current echolon. Still valuable for AST-only
  validators (signatures, logging, parameter_access) — their code is
  structurally sound, just not importable.

- ``MIGRATED_BASELINES`` — fixtures under
  echolon/tests/fixtures/baselines/, kept with current-era absolute
  imports. These can be imported by StrategyLoader, so they're the
  target set for ``component_integration``.

Principle 7: if a validator raises on any entry in its applicable
set, the validator is wrong, not the baseline. Fix the validator —
never grandfather the baseline.
"""
from pathlib import Path

import pytest

from echolon.strategy.validators.component_signatures import (
    validate_component_signatures,
)
from echolon.strategy.validators.component_integration import (
    validate_component_integration,
)
from echolon.strategy.validators.component_logging import (
    validate_component_logging,
)
from echolon.strategy.validators.parameter_access import (
    validate_parameter_access,
)


_BASELINES_ROOT = Path(
    "/home/yzj/projects/quantitive_trading/strategy_mining/"
    "DolphinQuantStrategy_al1/output"
)

_FIXTURES_ROOT = Path(__file__).parent.parent.parent / "fixtures" / "baselines"


def _discover_baselines() -> list[Path]:
    """Return sorted list of legacy baseline strategy_dir Paths to validate.

    We want strategies that plausibly passed full backtest previously.
    Heuristic: directory under output/ containing a ``code/`` subdir
    with all 4 component files + strategy_params.py + strategy.py.
    """
    if not _BASELINES_ROOT.exists():
        return []
    candidates = []
    required = {
        "entry.py", "exit.py", "risk.py", "sizer.py",
        "strategy.py", "strategy_params.py",
    }
    for version_dir in sorted(_BASELINES_ROOT.iterdir()):
        code_dir = version_dir / "code"
        if not code_dir.is_dir():
            continue
        present = {p.name for p in code_dir.iterdir() if p.is_file()}
        if required.issubset(present):
            candidates.append(code_dir)
    return candidates


def _discover_migrated_fixtures() -> list[Path]:
    """Baselines under echolon's own tests/fixtures/ that have been
    migrated to current echolon imports. These are safe inputs for the
    full validator suite including component_integration."""
    if not _FIXTURES_ROOT.exists():
        return []
    out = []
    required = {
        "entry.py", "exit.py", "risk.py", "sizer.py",
        "strategy.py", "strategy_params.py",
    }
    for fixture_dir in sorted(_FIXTURES_ROOT.iterdir()):
        if not fixture_dir.is_dir():
            continue
        present = {p.name for p in fixture_dir.iterdir() if p.is_file()}
        if required.issubset(present):
            out.append(fixture_dir)
    return out


LEGACY_BASELINES = _discover_baselines()
MIGRATED_BASELINES = _discover_migrated_fixtures()

ALL_BASELINES = LEGACY_BASELINES + MIGRATED_BASELINES


if not ALL_BASELINES:
    pytest.skip(
        f"No baseline strategies found under {_BASELINES_ROOT} or {_FIXTURES_ROOT}",
        allow_module_level=True,
    )


@pytest.fixture(
    params=ALL_BASELINES,
    ids=lambda p: f"{p.parent.name}/{p.name}" if p.parent.name == "baselines" else p.parent.name,
)
def any_baseline_strategy_dir(request):
    return request.param


# Legacy baselines omitted intentionally — their pre-v0.3 relative imports
# (``from ...core.base.base_component``) resolve to ``echolon.quant_engine.*``
# which no longer exists. This is environmental, not a validator concern.
# See plan doc validation principle 7 rationale.
@pytest.fixture(
    params=MIGRATED_BASELINES,
    ids=lambda p: p.name,
)
def migrated_baseline_strategy_dir(request):
    return request.param


def _format_findings(findings) -> str:
    """Pretty-print a Report's findings for assertion messages."""
    lines = []
    for f in findings:
        line_info = ""
        if "line" in f.context:
            line_info = f" (line {f.context['line']})"
        file_info = ""
        if "file" in f.context:
            # Just the filename for readability — full path clutters.
            file_info = f" in {Path(f.context['file']).name}"
        lines.append(f"  [{f.code}]{file_info}{line_info}: {f.message}")
    return "\n".join(lines)


def test_component_signatures_no_raise_on_baseline(any_baseline_strategy_dir):
    """Principle 7: if this fails, FIX THE VALIDATOR, not the baseline."""
    report = validate_component_signatures(strategy_dir=any_baseline_strategy_dir)
    assert not report.any_errors, (
        f"\nvalidator raised on known-good baseline: {any_baseline_strategy_dir}\n"
        f"findings:\n{_format_findings(report.findings)}\n\n"
        f"Principle 7: fix the validator (allowlist/loosen), not the baseline."
    )


def test_component_integration_no_raise_on_baseline(migrated_baseline_strategy_dir):
    """Principle 7: if this fails, FIX THE VALIDATOR, not the baseline.

    Only runs against MIGRATED_BASELINES — legacy baselines use pre-v0.3
    relative imports that no longer resolve under current echolon.
    """
    report = validate_component_integration(strategy_dir=migrated_baseline_strategy_dir)
    assert not report.any_errors, (
        f"\nvalidator raised on known-good baseline: {migrated_baseline_strategy_dir}\n"
        f"findings:\n{_format_findings(report.findings)}\n\n"
        f"Principle 7: fix the validator (allowlist/loosen), not the baseline."
    )


def test_component_logging_no_raise_on_baseline(any_baseline_strategy_dir):
    """Principle 7: if this fails, FIX THE VALIDATOR, not the baseline."""
    report = validate_component_logging(strategy_dir=any_baseline_strategy_dir)
    assert not report.any_errors, (
        f"\nvalidator raised on known-good baseline: {any_baseline_strategy_dir}\n"
        f"findings:\n{_format_findings(report.findings)}\n\n"
        f"Principle 7: fix the validator (allowlist/loosen), not the baseline."
    )


def test_parameter_access_no_raise_on_baseline(any_baseline_strategy_dir):
    """Principle 7: if this fails, FIX THE VALIDATOR, not the baseline.

    parameter_access is the highest-FP-risk of the 5 — this test is the
    single most important canary. A finding here almost certainly means
    the allowlist missed a legitimate pattern.
    """
    report = validate_parameter_access(strategy_dir=any_baseline_strategy_dir)
    assert not report.any_errors, (
        f"\nvalidator raised on known-good baseline: {any_baseline_strategy_dir}\n"
        f"findings:\n{_format_findings(report.findings)}\n\n"
        f"Principle 7: fix the validator (allowlist/loosen), not the baseline."
    )
