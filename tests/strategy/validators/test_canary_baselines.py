"""Binding FP guardrail (Part B1, validation principle 7).

Every new deterministic validator runs against archived known-good
strategies. Any finding = validator is over-tight, not the strategy.
Fix the validator (allowlist, loosen, or demote to warning). Never
grandfather the baseline.

Source of truth: strategy_mining/DolphinQuantStrategy_al1/output/<version>/code/
— these strategies have all been validated via backtest + champion selection
in prior R&D cycles; they represent the real-world distribution of human-
written strategy code.
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


def _discover_baselines() -> list[Path]:
    """Return sorted list of baseline strategy_dir Paths to validate.

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


BASELINES = _discover_baselines()


if not BASELINES:
    pytest.skip(
        f"No baseline strategies found under {_BASELINES_ROOT}",
        allow_module_level=True,
    )


@pytest.fixture(params=BASELINES, ids=lambda p: f"{p.parent.name}")
def baseline_strategy_dir(request):
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


def test_component_signatures_no_raise_on_baseline(baseline_strategy_dir):
    """Principle 7: if this fails, FIX THE VALIDATOR, not the baseline."""
    report = validate_component_signatures(strategy_dir=baseline_strategy_dir)
    assert not report.any_errors, (
        f"\nvalidator raised on known-good baseline: {baseline_strategy_dir}\n"
        f"findings:\n{_format_findings(report.findings)}\n\n"
        f"Principle 7: fix the validator (allowlist/loosen), not the baseline."
    )


def test_component_integration_no_raise_on_baseline(baseline_strategy_dir):
    """Principle 7: if this fails, FIX THE VALIDATOR, not the baseline."""
    report = validate_component_integration(strategy_dir=baseline_strategy_dir)
    assert not report.any_errors, (
        f"\nvalidator raised on known-good baseline: {baseline_strategy_dir}\n"
        f"findings:\n{_format_findings(report.findings)}\n\n"
        f"Principle 7: fix the validator (allowlist/loosen), not the baseline."
    )


def test_component_logging_no_raise_on_baseline(baseline_strategy_dir):
    """Principle 7: if this fails, FIX THE VALIDATOR, not the baseline."""
    report = validate_component_logging(strategy_dir=baseline_strategy_dir)
    assert not report.any_errors, (
        f"\nvalidator raised on known-good baseline: {baseline_strategy_dir}\n"
        f"findings:\n{_format_findings(report.findings)}\n\n"
        f"Principle 7: fix the validator (allowlist/loosen), not the baseline."
    )


def test_parameter_access_no_raise_on_baseline(baseline_strategy_dir):
    """Principle 7: if this fails, FIX THE VALIDATOR, not the baseline.

    parameter_access is the highest-FP-risk of the 5 — this test is the
    single most important canary. A finding here almost certainly means
    the allowlist missed a legitimate pattern.
    """
    report = validate_parameter_access(strategy_dir=baseline_strategy_dir)
    assert not report.any_errors, (
        f"\nvalidator raised on known-good baseline: {baseline_strategy_dir}\n"
        f"findings:\n{_format_findings(report.findings)}\n\n"
        f"Principle 7: fix the validator (allowlist/loosen), not the baseline."
    )
