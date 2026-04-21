"""Signal outputs with wrong enum casing must raise VAL-002."""
import pytest

from echolon.errors import ValidationError


def test_lowercase_signal_raises_val_002():
    from echolon.strategy.schemas import EntrySignalOutput

    # Test with a minimal construction that should fail at the `signal` validator
    with pytest.raises(ValidationError) as exc:
        EntrySignalOutput(
            signal="long",
            strength=0.8,
            type="entry",
            entry_reason="x",
            regime="trending_up",
        )
    assert exc.value.code == "VAL-002"
    assert "long" in str(exc.value)
    assert "LONG" in str(exc.value)


def test_valid_signal_accepted():
    from echolon.strategy.schemas import EntrySignalOutput

    sig = EntrySignalOutput(
        signal="LONG",
        strength=0.8,
        type="entry",
        entry_reason="x",
        regime="trending_up",
    )
    assert sig.signal == "LONG"


def test_hold_signal_accepted():
    from echolon.strategy.schemas import EntrySignalOutput

    sig = EntrySignalOutput(
        signal="HOLD",
        strength=0.0,
        type="entry",
        entry_reason="x",
        regime="trending_up",
    )
    assert sig.signal == "HOLD"


def test_short_signal_on_exit_output():
    from echolon.strategy.schemas import ExitSignalOutput

    # ExitSignalOutput requires: should_exit, exit_reason, position_size,
    # bars_since_entry. The `signal` field doesn't exist on ExitSignalOutput
    # currently — we add the same validator there for consistency once LLM
    # authors include `signal` as an extra (extra='allow'). This test exercises
    # the validator by providing `signal` explicitly.
    sig = ExitSignalOutput(
        signal="SHORT",
        should_exit=True,
        exit_reason="stop hit",
        position_size=1.0,
        bars_since_entry=5,
    )
    assert sig.signal == "SHORT"


def test_missing_required_field_raises_val_001():
    """EntrySignalOutput without a required field raises VAL-001 (not pydantic generic)."""
    from echolon.strategy.schemas import EntrySignalOutput
    from echolon.errors import ValidationError

    with pytest.raises(ValidationError) as exc:
        # Omit 'entry_reason' (required)
        EntrySignalOutput(signal="LONG", strength=0.8, type="entry")
    assert exc.value.code == "VAL-001"
    assert "entry_reason" in str(exc.value)


def test_extra_field_is_forbidden_on_entry():
    """EntrySignalOutput rejects fields not declared on the schema."""
    from echolon.strategy.schemas import EntrySignalOutput
    import pydantic

    with pytest.raises(pydantic.ValidationError):
        EntrySignalOutput(
            signal="LONG",
            strength=0.8,
            type="entry",
            entry_reason="x",
            regime="trending_up",
            custom_unknown_field=42,  # not in schema
        )


def test_extra_field_is_forbidden_on_exit():
    """ExitSignalOutput rejects fields not declared on the schema."""
    from echolon.strategy.schemas import ExitSignalOutput
    import pydantic

    # Pick whatever the ExitSignalOutput required-field set is from Phase 4.3
    # discovery — omit nothing; add a spurious field.
    with pytest.raises(pydantic.ValidationError):
        ExitSignalOutput(
            signal="SHORT",
            should_exit=True,
            exit_reason="stop hit",
            position_size=1.0,
            bars_since_entry=5,
            bogus_field=1,
        )
