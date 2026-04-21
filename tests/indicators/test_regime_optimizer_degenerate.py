"""When every Optuna trial fails a hard constraint, the optimizer must return
a result flagged with code IND-004 so the caller can refuse to deploy the params."""


def test_build_summary_result_flags_degenerate():
    from echolon.indicators.optimization.interday_regime_optimizer import (
        _build_summary_result,
    )

    degenerate_trials = [
        {"trial_number": 0, "constraint": "MIN_RETURN_SEPARATION"},
        {"trial_number": 1, "constraint": "MIN_RETURN_SEPARATION"},
        {"trial_number": 2, "constraint": "min_ranging_pct"},
    ]
    summary = _build_summary_result(
        n_trials=3,
        degenerate_trials=degenerate_trials,
        best_params={"fast_ma_period": 10},
    )
    assert summary["degenerate"] is True
    assert summary["code"] == "IND-004"
    assert summary["trials_rejected"] == 3
    assert summary["n_trials"] == 3
    # Rejected reasons summarize per-constraint counts
    assert summary["rejected_reasons"]["MIN_RETURN_SEPARATION"] == 2
    assert summary["rejected_reasons"]["min_ranging_pct"] == 1


def test_build_summary_result_not_degenerate_when_partial():
    """When only some trials were rejected, the result is NOT flagged degenerate."""
    from echolon.indicators.optimization.interday_regime_optimizer import (
        _build_summary_result,
    )

    summary = _build_summary_result(
        n_trials=10,
        degenerate_trials=[{"trial_number": 1, "constraint": "x"}],
        best_params={"fast_ma_period": 10},
    )
    assert summary["degenerate"] is False
    # degenerate=False → no "code" key (LLM caller knows to check `degenerate`)
    assert "code" not in summary
    assert summary["trials_rejected"] == 1
    assert summary["n_trials"] == 10


def test_build_summary_result_empty_trials_list():
    """Zero trials → not degenerate (there's nothing to reject)."""
    from echolon.indicators.optimization.interday_regime_optimizer import (
        _build_summary_result,
    )

    summary = _build_summary_result(
        n_trials=0,
        degenerate_trials=[],
        best_params={},
    )
    assert summary["degenerate"] is False
