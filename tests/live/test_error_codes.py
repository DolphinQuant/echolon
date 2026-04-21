"""Live-layer errors use LIV-001/002/003 catalog codes."""
import sys
from unittest.mock import MagicMock

# Stub out xtquant (Windows-only broker SDK) before importing qmt_client.
# The helpers under test do not touch xtquant; the stubs only satisfy the
# module-level imports at qmt_client.py:42-44.
for _mod_name in (
    "xtquant",
    "xtquant.xtconstant",
    "xtquant.xtdata",
    "xtquant.xttrader",
    "xtquant.xttype",
):
    sys.modules.setdefault(_mod_name, MagicMock())

import pytest  # noqa: E402

from echolon.errors import EchelonError  # noqa: E402


def test_raise_broker_unavailable_liv_001():
    from echolon.live.platforms.miniqmt.qmt_client import _raise_broker_unavailable

    with pytest.raises(EchelonError) as exc:
        _raise_broker_unavailable(
            account_id="test-acct-123",
            error="connection refused",
        )
    assert exc.value.code == "LIV-001"
    assert "test-acct-123" in str(exc.value)


def test_raise_order_rejected_liv_002():
    from echolon.live.platforms.miniqmt.qmt_client import _raise_order_rejected

    with pytest.raises(EchelonError) as exc:
        _raise_order_rejected(
            contract="al2404",
            direction="BUY",
            price=20000.0,
            size=5,
            broker_status=57,
            broker_message="price outside day range",
        )
    assert exc.value.code == "LIV-002"
    assert "al2404" in str(exc.value)


def test_raise_qmt_callback_error_liv_003():
    from echolon.live.platforms.miniqmt.qmt_client import _raise_qmt_callback_error

    with pytest.raises(EchelonError) as exc:
        _raise_qmt_callback_error(
            seq_id=1234,
            qmt_status=57,
            raw={"foo": "bar"},
        )
    assert exc.value.code == "LIV-003"
    # echo_status should be derived from qmt_status; 57 -> REJECTED
    assert "REJECTED" in str(exc.value) or "57" in str(exc.value)


def test_qmt_callback_error_unknown_status():
    """Unknown QMT status code maps to UNKNOWN_<status> instead of raising."""
    from echolon.live.platforms.miniqmt.qmt_client import _raise_qmt_callback_error

    with pytest.raises(EchelonError) as exc:
        _raise_qmt_callback_error(
            seq_id=999,
            qmt_status=12345,  # not in the status map
            raw="raw payload",
        )
    assert exc.value.code == "LIV-003"
    assert "UNKNOWN" in str(exc.value) or "12345" in str(exc.value)
