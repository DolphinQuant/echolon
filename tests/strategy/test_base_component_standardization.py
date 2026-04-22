"""Tests for BaseComponent typed Params + declarative hooks (Task 23)."""
import pytest


def test_base_component_accepts_typed_params():
    """A concrete component using the new Params dataclass pattern must construct cleanly."""
    from echolon.strategy.component import BaseComponent
    from dataclasses import dataclass

    @dataclass
    class MyParams:
        printlog: bool = False
        threshold: float = 0.5

    class MyComponent(BaseComponent):
        Params = MyParams
        hooks = ()  # declarative hooks list; empty OK

        def evaluate(self, bar):
            return None

    instance = MyComponent(params=MyParams(threshold=0.7))
    assert instance.params.threshold == 0.7
    assert instance.params.printlog is False


def test_base_component_auto_derives_indicator_list_when_declared():
    """Component can declare `indicators: tuple[str, ...]` — auto-surfaced."""
    from echolon.strategy.component import BaseComponent
    from dataclasses import dataclass

    @dataclass
    class P:
        printlog: bool = False

    class RsiEntry(BaseComponent):
        Params = P
        hooks = ()
        indicators = ("rsi_14", "atr_20")

        def evaluate(self, bar):
            return None

    assert set(RsiEntry.indicators) == {"rsi_14", "atr_20"}


def test_base_component_backward_compat_no_params_dataclass():
    """Legacy components without a Params dataclass still construct."""
    from echolon.strategy.component import BaseComponent

    class LegacyComponent(BaseComponent):
        def evaluate(self, bar):
            return None

    instance = LegacyComponent(params={"printlog": False, "threshold": 0.5})
    # Legacy dict-based params still work
    assert instance.params is not None
