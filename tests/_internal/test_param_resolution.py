"""Golden regression tests for the trial→deployed parameter resolution fix.

The fixture is SYNTHETIC (public-repo safe — no live strategy parameterization)
but structurally faithful: it reproduces the four defect mechanisms the
incident proved against production artifacts:

  1. Family-A flat keys whose canonical names ALREADY carry the component
     prefix + Family-B double-prefixed default twins — the strip-once mappers
     orphan the optimized value and deliver the default;
  2. an in-function SHARED sizer copy of an exit value — unrecoverable from
     the flat dict by any name-based merge (the copy happens inside
     optuna_search_space);
  3. a BARE optuna key (silently dropped by the live mapper; routed to a
     top-level extra by the backtest mapper) with a same-destination Family-B
     twin;
  4. an int distribution whose value round-trips through CSV/pandas as float —
     replay must re-cast.

Fixture ground truth (synthetic values):
  exit_down_stop_mult: default 1.0 deployed by the legacy mapping, optimized
  1.444 orphaned; trailing_mult: default 3.0, optimized 2.222 bare-keyed;
  alpha_period: optimized 21 (arrives as 21.0).
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from echolon._internal.param_resolution import resolve_via_merge, resolve_via_replay
from echolon._internal.strategy_files import (
    ResolvedParams,
    load_resolved_params,
    save_resolved_params,
    trial_params_fingerprint,
)

FIXTURE = Path(__file__).parent.parent / "fixtures" / "param_resolution" / "synthetic_s1"

OPTIMIZED_STOP = 1.444
DEFAULT_STOP = 1.0
OPTIMIZED_TRAIL = 2.222


def _load_fixture():
    """Load the synthetic strategy_params module + its trial JSON."""
    spec = importlib.util.spec_from_file_location(
        "sp_synthetic", FIXTURE / "strategy_params.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    trial = json.loads((FIXTURE / "selected_robust_trial.json").read_text())
    return module, trial


# ---- resolve_via_replay: the authoritative resolver -------------------------


def test_replay_recovers_orphaned_canonical_prefixed_values():
    sp, trial = _load_fixture()
    nested = resolve_via_replay(sp.optuna_search_space, trial["params"])
    assert nested is not None
    assert nested["exit_params"]["exit_down_stop_mult"] == OPTIMIZED_STOP
    assert nested["entry_params"]["entry_gate_threshold"] == pytest.approx(0.777)
    # int distribution round-trips through pandas as float — replay re-casts
    assert nested["entry_params"]["alpha_period"] == 21
    assert isinstance(nested["entry_params"]["alpha_period"], int)


def test_replay_recovers_shared_sizer_copy_merge_cannot():
    """The in-function shared copy only exists in the replay — the flat dict's
    sizer twin carries the stale default and no name merge can know better."""
    sp, trial = _load_fixture()
    nested = resolve_via_replay(sp.optuna_search_space, trial["params"])
    assert nested["sizer_params"]["exit_down_stop_mult"] == OPTIMIZED_STOP

    merged = resolve_via_merge(trial["params"], sp.DEFAULT_PARAMS)
    # documented limitation: Family-B twin (default) wins in the flat dict
    assert merged["sizer_params"]["exit_down_stop_mult"] == DEFAULT_STOP


def test_replay_recovers_bare_optuna_key():
    sp, trial = _load_fixture()
    nested = resolve_via_replay(sp.optuna_search_space, trial["params"])
    assert nested["sizer_params"]["trailing_mult"] == OPTIMIZED_TRAIL
    assert nested["exit_params"]["exit_atr_period"] == 17


def test_replay_returns_none_on_missing_suggested_name():
    sp, trial = _load_fixture()
    crippled = {k: v for k, v in trial["params"].items() if k != "exit_atr_period"}
    assert resolve_via_replay(sp.optuna_search_space, crippled) is None


def test_replay_returns_none_on_broken_search_space():
    def exploding(_trial):
        raise RuntimeError("boom")

    assert resolve_via_replay(exploding, {"x": 1}) is None


def test_replay_canonicalizes_categorical_types():
    """CSV round-trips deliver 10.0 / 1.0 where the optimizer had int 10 /
    True; cross-type equality (10.0 in [10, 20]) must not leak the float
    through — the canonical choice object is restored."""

    def space(trial):
        return {
            "x_params": {
                "n": trial.suggest_categorical("n", [10, 20]),
                "flag": trial.suggest_categorical("flag", [True, False]),
                "label": trial.suggest_categorical("label", ["a", "b"]),
            }
        }

    nested = resolve_via_replay(space, {"n": 10.0, "flag": 1.0, "label": "b"})
    assert nested["x_params"]["n"] == 10 and isinstance(nested["x_params"]["n"], int)
    assert nested["x_params"]["flag"] is True
    assert nested["x_params"]["label"] == "b"


# ---- resolve_via_merge: tier behavior (fallback/diagnostics only) ----------


def test_merge_tier1_canonical_prefixed_beats_tier2_double_prefixed():
    """The flat dict carries BOTH 'exit_down_stop_mult' (Family A, canonical
    name == member of exit_params) and 'exit_exit_down_stop_mult' (Family B).
    Tier 1 must win regardless of iteration order."""
    sp, trial = _load_fixture()
    merged = resolve_via_merge(trial["params"], sp.DEFAULT_PARAMS)
    assert merged["exit_params"]["exit_down_stop_mult"] == OPTIMIZED_STOP
    assert merged["entry_params"]["entry_gate_threshold"] == pytest.approx(0.777)


def test_merge_tier2_strips_generator_prefix():
    sp, trial = _load_fixture()
    merged = resolve_via_merge(trial["params"], sp.DEFAULT_PARAMS)
    # 'entry_alpha_period' (generator-prefixed; canonical 'alpha_period')
    assert merged["entry_params"]["alpha_period"] == 21.0


def test_merge_tier3_loses_to_family_b_twin_replay_does_not():
    """The bare optuna name (optimized, tier 3) collides with the Family-B
    twin 'sizer_trailing_mult' (default, tier 2) on the same destination —
    lowest tier wins, so the merge keeps the DEFAULT. Genuinely ambiguous from
    names alone: one more proof merge is diagnostics-only."""
    sp, trial = _load_fixture()
    merged = resolve_via_merge(trial["params"], sp.DEFAULT_PARAMS)
    assert merged["sizer_params"]["trailing_mult"] == 3.0  # limitation
    nested = resolve_via_replay(sp.optuna_search_space, trial["params"])
    assert nested["sizer_params"]["trailing_mult"] == OPTIMIZED_TRAIL


def test_merge_tier3_routes_bare_key_when_unambiguous():
    defaults = {"sizer_params": {"trailing_mult": 3.0, "lots": 1}}
    merged = resolve_via_merge({"trailing_mult": 2.222}, defaults)
    assert merged["sizer_params"]["trailing_mult"] == 2.222


# ---- legacy mapper: the defect must be PRESERVED on the fallback path -------


def test_legacy_backtest_mapper_still_exhibits_the_defect():
    """The legacy path must stay byte-identical (it is today's OOS-validated,
    live-tracked behavior) — the fix is opt-in via the artifact, never a
    silent change of the fallback."""
    from echolon.backtest.engine.backtest_runner import BacktestRunner

    sp, trial = _load_fixture()
    mapped = BacktestRunner._map_optuna_params(trial["params"], sp.DEFAULT_PARAMS)
    assert mapped["exit_params"]["exit_down_stop_mult"] == DEFAULT_STOP
    # the optimized value is stranded on the orphan key nothing reads
    assert mapped["exit_params"]["down_stop_mult"] == OPTIMIZED_STOP
    # the bare key lands as a top-level extra (absorbed inert downstream)
    assert mapped["trailing_mult"] == OPTIMIZED_TRAIL


# ---- artifact IO ------------------------------------------------------------


def test_resolved_params_roundtrip(tmp_path):
    components = {"entry_params": {"a": 1}, "exit_params": {"b": 2.5}}
    provenance = {"trial_number": 7, "trial_params_sha256": "ab" * 32}
    out = save_resolved_params(tmp_path, components, provenance=provenance)
    assert out.name == "resolved_params.json"
    loaded = load_resolved_params(tmp_path)
    assert isinstance(loaded, ResolvedParams)
    assert loaded.version == 1
    assert loaded.components == components
    assert loaded.provenance == provenance


def test_load_resolved_params_missing_returns_none(tmp_path):
    assert load_resolved_params(tmp_path) is None


def test_load_resolved_params_unknown_version_raises(tmp_path):
    (tmp_path / "resolved_params.json").write_text(json.dumps({"version": 2}))
    with pytest.raises(ValueError, match="version"):
        load_resolved_params(tmp_path)


def test_fingerprint_is_numpy_stable():
    np = pytest.importorskip("numpy")
    py_side = {"exit_atr_period": 17.0, "x": 1.444}
    np_side = {"exit_atr_period": np.float64(17.0), "x": np.float64(1.444)}
    assert trial_params_fingerprint(py_side) == trial_params_fingerprint(np_side)
    assert trial_params_fingerprint(py_side) != trial_params_fingerprint({"x": 1.0})


# ---- exporter: TrialSelector companion emission ------------------------------


def _make_selector(tmp_path, search_space_fn, default_params):
    """Minimal TrialSelector: a tiny synthetic trials CSV satisfies __init__."""
    import pandas as pd

    from echolon.backtest.optimization.select_best_trial import TrialSelector

    csv_path = tmp_path / "optimization_trials.csv"
    pd.DataFrame(
        {
            "number": [0, 1],
            "values_0": [1.0, 1.2],
            "values_1": [-10.0, -9.0],
            "values_2": [12.0, 14.0],
            "params_entry_alpha_period": [12, 21],
        }
    ).to_csv(csv_path, index=False)
    return TrialSelector(
        trial_data_path=str(csv_path),
        output_dir=str(tmp_path / "out"),
        default_params=default_params,
        strategy_code_dir=tmp_path / "code",
        search_space_fn=search_space_fn,
    )


def test_exporter_writes_sha_matched_resolved_artifact(tmp_path):
    sp, trial = _load_fixture()
    selector = _make_selector(tmp_path, sp.optuna_search_space, sp.DEFAULT_PARAMS)
    selector._export_resolved_params(
        {"trial_number": trial["trial_number"], "params": trial["params"]}
    )
    resolved = load_resolved_params(tmp_path / "code")
    assert resolved is not None
    assert resolved.provenance["trial_number"] == trial["trial_number"]
    assert resolved.provenance["trial_params_sha256"] == trial_params_fingerprint(
        trial["params"]
    )
    assert resolved.components["exit_params"]["exit_down_stop_mult"] == OPTIMIZED_STOP


def test_exporter_without_search_space_fn_discards_stale_artifact(tmp_path):
    """A trial save WITHOUT companion export must remove any older companion —
    a leftover artifact must never pair with a newer trial file."""
    sp, trial = _load_fixture()
    code_dir = tmp_path / "code"
    code_dir.mkdir()
    (code_dir / "resolved_params.json").write_text(
        json.dumps({"version": 1, "components": {}, "provenance": {}})
    )
    selector = _make_selector(tmp_path, None, sp.DEFAULT_PARAMS)
    selector._export_resolved_params({"trial_number": 1, "params": trial["params"]})
    assert load_resolved_params(code_dir) is None


def test_exporter_replay_failure_discards_stale_and_does_not_raise(tmp_path):
    sp, _ = _load_fixture()
    code_dir = tmp_path / "code"
    code_dir.mkdir()
    (code_dir / "resolved_params.json").write_text(
        json.dumps({"version": 1, "components": {}, "provenance": {}})
    )
    selector = _make_selector(tmp_path, sp.optuna_search_space, sp.DEFAULT_PARAMS)
    selector._export_resolved_params({"trial_number": 1, "params": {}})  # replay fails
    assert load_resolved_params(code_dir) is None


# ---- WFA runner: the stale-read regression guard -----------------------------


def test_wfa_selector_writes_where_run_best_trial_reads(tmp_path):
    """THE stale-read incident pin: the per-window TrialSelector must write its
    selection to paths.strategy_code_dir (what run_best_trial reads), never to
    TrialSelector's env-based default (a different dir under run isolation —
    proven incident: 5 windows, 5 selected trials, ONE identical executed
    vector from the stale file at the read path)."""
    import pandas as pd

    from echolon.backtest.wfa.runner import WFARunner

    csv_path = tmp_path / "optimization_trials.csv"
    pd.DataFrame(
        {
            "number": [0],
            "values_0": [1.0],
            "values_1": [-10.0],
            "values_2": [12.0],
            "params_entry_alpha_period": [21],
        }
    ).to_csv(csv_path, index=False)

    runner = WFARunner.__new__(WFARunner)  # bypass heavy __init__; test the seam
    runner._paths = SimpleNamespace(strategy_code_dir=tmp_path / "run_code_dir")
    runner.config = SimpleNamespace(max_drawdown_threshold=15.0)

    selector = runner._build_selector(
        trials_csv_path=csv_path,
        window_dir=tmp_path / "window",
        default_params={},
        apply_shared_params_fn=None,
        param_classifications=None,
        search_space_fn=None,
    )
    assert selector.selected_trial_output_dir == tmp_path / "run_code_dir"


# ---- consumer: BacktestRunner gate -------------------------------------------


def _stage_pair(tmp_path, sp, trial):
    """Stage a matched trial + resolved pair the way the exporter would."""
    (tmp_path / "selected_robust_trial.json").write_text(json.dumps(trial))
    nested = resolve_via_replay(sp.optuna_search_space, trial["params"])
    save_resolved_params(
        tmp_path,
        nested,
        provenance={
            "trial_number": trial["trial_number"],
            "trial_params_sha256": trial_params_fingerprint(trial["params"]),
        },
    )


def test_consumer_prefers_sha_matched_resolved_artifact(tmp_path):
    from echolon.backtest.engine.backtest_runner import BacktestRunner

    sp, trial = _load_fixture()
    _stage_pair(tmp_path, sp, trial)
    params_path = str(tmp_path / "selected_robust_trial.json")
    effective = BacktestRunner._resolved_strategy_params(params_path, trial["params"])
    assert effective is not None
    assert effective["exit_params"]["exit_down_stop_mult"] == OPTIMIZED_STOP
    # the resolved path carries no orphan keys
    assert "down_stop_mult" not in effective["exit_params"]


def test_consumer_falls_back_on_provenance_mismatch(tmp_path):
    from echolon.backtest.engine.backtest_runner import BacktestRunner

    sp, trial = _load_fixture()
    _stage_pair(tmp_path, sp, trial)
    # Simulate a STALE pair: trial params changed after the artifact was written
    mutated = dict(trial["params"])
    mutated["exit_atr_period"] = 11.0
    effective = BacktestRunner._resolved_strategy_params(
        str(tmp_path / "selected_robust_trial.json"), mutated
    )
    assert effective is None


def test_consumer_falls_back_on_missing_provenance_sha(tmp_path):
    """The sha is load-bearing: an artifact that cannot prove it pairs with
    THIS trial file is never trusted (a hand-edited / truncated artifact must
    not bypass the gate)."""
    from echolon.backtest.engine.backtest_runner import BacktestRunner

    sp, trial = _load_fixture()
    (tmp_path / "selected_robust_trial.json").write_text(json.dumps(trial))
    save_resolved_params(
        tmp_path,
        {"entry_params": {"stale": True}},
        provenance={"trial_number": 99},  # no sha
    )
    effective = BacktestRunner._resolved_strategy_params(
        str(tmp_path / "selected_robust_trial.json"), trial["params"]
    )
    assert effective is None


def test_consumer_absent_artifact_returns_none(tmp_path):
    from echolon.backtest.engine.backtest_runner import BacktestRunner

    (tmp_path / "selected_robust_trial.json").write_text("{}")
    assert (
        BacktestRunner._resolved_strategy_params(
            str(tmp_path / "selected_robust_trial.json"), {"x": 1}
        )
        is None
    )


def test_consumer_malformed_artifact_never_raises(tmp_path):
    from echolon.backtest.engine.backtest_runner import BacktestRunner

    (tmp_path / "resolved_params.json").write_text("{not json")
    assert (
        BacktestRunner._resolved_strategy_params(
            str(tmp_path / "selected_robust_trial.json"), {"x": 1}
        )
        is None
    )
