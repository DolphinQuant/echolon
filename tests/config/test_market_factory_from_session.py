"""Phase P1 — MarketFactory.from_session must forward the resolved session_dir.

Regression fixture for the bug where from_session() ignored the already-resolved
session_dir and fell back to TradingTarget.load()'s broken default
(echolon/echolon/session/state.json inside the installed package).
"""
import json
from pathlib import Path

import pytest


_MINIMAL_STATE = {
    "user_request": "test fixture",
    "market": "SHFE",
    "market_full_name": "Shanghai Futures Exchange",
    "instrument": "aluminum",
    "instrument_code": "al",
    "frequency": "interday",
    "bar_size": "1d",
    "initial_capital": 200000.0,
}


def _setup_session(tmp_path: Path) -> tuple[Path, Path]:
    """Create a tmp session_dir + output_dir and return them."""
    session_dir = tmp_path / "session"
    session_dir.mkdir()
    (session_dir / "state.json").write_text(json.dumps(_MINIMAL_STATE, indent=2))
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    return session_dir, output_dir


def test_from_session_reads_session_state_when_output_target_missing(tmp_path):
    """Core regression. The bug: from_session fell through to TradingTarget.load(None)
    which defaulted to an echolon-package-internal path. The fix forwards the
    already-resolved session_dir so state.json is found in the caller's session dir.
    """
    from echolon.config.markets.factory import MarketFactory

    session_dir, output_dir = _setup_session(tmp_path)
    # output/target.json does NOT exist — force the state.json path.

    ctx = MarketFactory.from_session(
        session_dir=session_dir,
        output_dir=output_dir,
    )
    assert ctx.market_code == "SHFE"
    assert ctx.instrument_code == "al"
    assert ctx.frequency == "interday"
    assert ctx.bar_size == "1d"


def test_from_session_prefers_output_target_when_both_exist(tmp_path):
    """output/target.json fast-path still takes precedence — do not regress."""
    from echolon.config.markets.factory import MarketFactory

    session_dir, output_dir = _setup_session(tmp_path)

    # Write an output/target.json with a DIFFERENT instrument to prove precedence
    integrated_target = dict(_MINIMAL_STATE)
    integrated_target["instrument"] = "copper"
    integrated_target["instrument_code"] = "cu"
    (output_dir / "target.json").write_text(json.dumps(integrated_target))

    ctx = MarketFactory.from_session(
        session_dir=session_dir,
        output_dir=output_dir,
    )
    # Must be the output/target.json value, not session/state.json
    assert ctx.instrument_code == "cu"


def test_from_session_explicit_session_path_overrides_session_dir(tmp_path):
    """Explicit session_path= still wins over session_dir-resolved default."""
    from echolon.config.markets.factory import MarketFactory

    session_dir, output_dir = _setup_session(tmp_path)

    # An alternate state.json in a different location
    alt = tmp_path / "alt_state.json"
    alt_state = dict(_MINIMAL_STATE)
    alt_state["instrument_code"] = "zn"
    alt_state["instrument"] = "zinc"
    alt.write_text(json.dumps(alt_state))

    ctx = MarketFactory.from_session(
        session_path=str(alt),
        session_dir=session_dir,
        output_dir=output_dir,
    )
    assert ctx.instrument_code == "zn"


def test_load_target_respects_session_dir(tmp_path):
    """load_target() has the same bug shape as from_session — must be fixed too."""
    from echolon.config.markets.factory import MarketFactory

    session_dir, output_dir = _setup_session(tmp_path)
    target = MarketFactory.load_target(
        session_dir=session_dir,
        output_dir=output_dir,
    )
    assert target.market == "SHFE"
    assert target.instrument_code == "al"


def test_trading_target_load_no_args_uses_paths_config(tmp_path, monkeypatch):
    """TradingTarget.load() with no args must resolve via PathsConfig.from_env(),
    not the broken `Path(__file__).parent.parent.parent.parent / "session"` default.

    Simulates a fresh end-user script: set ECHOLON_PROJECT_ROOT to a tmp dir with
    a session/state.json in it; TradingTarget.load() should find it.
    """
    from echolon.config.markets.core.trading_target import TradingTarget

    _setup_session(tmp_path)
    monkeypatch.setenv("ECHOLON_PROJECT_ROOT", str(tmp_path))
    target = TradingTarget.load()
    assert target.market == "SHFE"
    assert target.instrument_code == "al"


def test_trading_target_load_missing_raises_informative_error(tmp_path, monkeypatch):
    """If no state.json exists anywhere reachable, raise FileNotFoundError with
    a path that points at the project-root-resolved location, not an
    echolon-package-internal path."""
    from echolon.config.markets.core.trading_target import TradingTarget

    monkeypatch.setenv("ECHOLON_PROJECT_ROOT", str(tmp_path))  # empty tmp
    with pytest.raises(FileNotFoundError) as exc:
        TradingTarget.load()
    # The error must point at the resolved project-root session, not echolon's
    # installed-package location.
    assert "echolon/echolon/session" not in str(exc.value)
    assert str(tmp_path) in str(exc.value) or "session" in str(exc.value)
