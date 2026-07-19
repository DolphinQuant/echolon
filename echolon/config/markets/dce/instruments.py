"""DCE (Dalian Commodity Exchange) instrument specifications.

Panel-v5 expansion (FV3 WP-X1b). Canonical declarative spec source for the DCE
products added this round, mirroring ``echolon/config/markets/shfe/instruments``.

Authoritative fields:
    ``multiplier`` (交易单位) and ``tick_size`` are exchange contract
    specifications, verified 2026-07-19 against akshare ``futures_fees_info``
    (合约乘数/最小跳动).

Non-authoritative fields:
    ``margin_rate`` and ``commission`` are broker-observed snapshots (akshare
    ``futures_fees_info``, updated 2026-07-18) and change over time. Session
    windows are NOT authored here (no intraday session/phase model is consumed
    by the panel-v5 pipeline); ``sessions`` is left empty and
    ``has_night_session`` unset by design.
"""

from typing import Dict

from ..core.types import InstrumentSpec


INSTRUMENTS: Dict[str, InstrumentSpec] = {
    'eb': InstrumentSpec(
        code='eb',
        name='styrene',
        market='DCE',
        multiplier=5.0,           # 5吨/手 — verified
        tick_size=1.0,            # 1元/吨 — verified
        margin_rate=0.20,         # akshare futures_fees_info snapshot 2026-07-18
        commission=1.01,          # akshare snapshot; broker-observed, time-varying
        commission_type='per_contract',
        currency='CNY',
        trading_unit='lots',
        min_order_size=1.0,
        has_night_session=False,
        sessions=[],
    ),
    'a': InstrumentSpec(
        code='a',
        name='soybean_no1',
        market='DCE',
        multiplier=10.0,          # 10吨/手 — verified
        tick_size=1.0,            # 1元/吨 — verified
        margin_rate=0.07,         # akshare futures_fees_info snapshot 2026-07-18
        commission=2.01,          # akshare snapshot; broker-observed, time-varying
        commission_type='per_contract',
        currency='CNY',
        trading_unit='lots',
        min_order_size=1.0,
        has_night_session=False,
        sessions=[],
    ),
    'b': InstrumentSpec(
        code='b',
        name='soybean_no2',
        market='DCE',
        multiplier=10.0,          # 10吨/手 — verified
        tick_size=1.0,            # 1元/吨 — verified
        margin_rate=0.10,         # akshare futures_fees_info snapshot 2026-07-18
        commission=1.01,          # akshare snapshot; broker-observed, time-varying
        commission_type='per_contract',
        currency='CNY',
        trading_unit='lots',
        min_order_size=1.0,
        has_night_session=False,
        sessions=[],
    ),
    'cs': InstrumentSpec(
        code='cs',
        name='corn_starch',
        market='DCE',
        multiplier=10.0,          # 10吨/手 — verified
        tick_size=1.0,            # 1元/吨 — verified
        margin_rate=0.06,         # akshare futures_fees_info snapshot 2026-07-18
        commission=1.51,          # akshare snapshot; broker-observed, time-varying
        commission_type='per_contract',
        currency='CNY',
        trading_unit='lots',
        min_order_size=1.0,
        has_night_session=False,
        sessions=[],
    ),
}


def get_instrument(code: str) -> InstrumentSpec:
    """Get instrument specification by code."""
    return INSTRUMENTS[code.lower()]


def list_instruments() -> list:
    """Get list of all instrument codes."""
    return list(INSTRUMENTS.keys())
