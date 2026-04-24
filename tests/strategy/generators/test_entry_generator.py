"""Acceptance tests for entry_generator.

Scaffolder contract:
- Output is a pure-Python module importable via echolon.strategy.loader.
- Defines a class named ``entry_rule`` that subclasses BaseComponent.
- Class exposes a ``generate_signal`` method that returns an EntrySignalOutput
  with ``signal='HOLD'`` (trivial default — agent designs the business logic).
- No platform-specific imports (backtrader, miniQMT, etc.).
"""
from pathlib import Path

from echolon.strategy.generators.entry_generator import generate_entry
from echolon.strategy.loader import StrategyLoader
from echolon.strategy.schemas import EntrySignalOutput


def test_entry_generator_writes_module_file(tmp_path: Path):
    out = generate_entry(strategy_dir=tmp_path)
    assert out == tmp_path / "entry.py"
    assert out.exists()
    assert out.read_text(encoding="utf-8").strip() != ""


def test_entry_generator_produces_loadable_module(tmp_path: Path):
    generate_entry(strategy_dir=tmp_path)
    loader = StrategyLoader(tmp_path)
    mod = loader.load_module("entry")

    assert hasattr(mod, "entry_rule"), "class name must match loader.EXPECTED_CLASSES"
    cls = mod.entry_rule
    assert hasattr(cls, "generate_signal"), "must expose generate_signal"


def test_entry_generator_returns_trivial_hold(tmp_path: Path):
    """Scaffolder returns HOLD by default — agent designs pathways later."""
    generate_entry(strategy_dir=tmp_path)
    loader = StrategyLoader(tmp_path)
    mod = loader.load_module("entry")

    class _FakeEngine:
        current_regime = "ranging"

        def get_frequency_context(self):
            return None

        def get_market_adapter(self):
            return None

        def get_trading_context(self):
            return None

        def get_market_data(self):
            return None

        def get_portfolio(self):
            return None

        def get_logger(self):
            return None

        def get_strategy_logger(self):
            return None

    inst = mod.entry_rule(trading_engine=_FakeEngine())
    out = inst.generate_signal()
    assert isinstance(out, EntrySignalOutput)
    assert out.signal == "HOLD"


def test_entry_generator_has_no_platform_imports(tmp_path: Path):
    generate_entry(strategy_dir=tmp_path)
    text = (tmp_path / "entry.py").read_text(encoding="utf-8")
    for forbidden in ("import backtrader", "from backtrader", "xtdata", "miniQMT"):
        assert forbidden not in text, f"platform-agnostic rule violated: {forbidden}"
