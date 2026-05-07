"""Order-routing policy constants.

Single source of truth for tunable order-placement knobs. See
``docs/superpowers/designs/2026-05-07-miniqmt-architecture-and-order-logic.md``
section 21 for derivation.

Rationale for ``BUFFER_TICKS_BY_ATTEMPT[1] = 4``:
    Yesterday's al_s1 ENTRY_SHORT bug (2026-05-06 21:00:07) submitted
    FIX_PRICE @ bid1=24645 with zero buffer. The market moved through
    24645 within seconds and never returned. A 4-tick buffer (20 CNY for
    al, price_tick=5) keeps the order marketable for the first ~60s of
    the night session.
"""

from typing import Dict


# ----- Layer 1 — Tick buffer ------------------------------------------------

BUFFER_TICKS_BY_ATTEMPT: Dict[int, int] = {1: 4, 2: 8, 3: 16}
DEFAULT_BUFFER_TICKS: int = 4


# ----- Layer 2 — Watchdog timing --------------------------------------------

WATCHDOG_TICK_S: float = 0.1            # main loop polling cadence
QUIESCENCE_WINDOW_S: float = 1.5        # WINDING_DOWN -> TERMINAL after this gap
DEADLINE_DEFAULT_S: float = 30.0        # cancel-and-resubmit after this idle
TICK_SNAPSHOT_MAX_AGE_S: float = 2.0    # tick freshness threshold


# ----- Layer 2 — Resubmit policy by recovery class --------------------------

MAX_ATTEMPTS_BY_CLASS: Dict[str, int] = {
    "ENTRY": 3,
    "EXIT": 5,
    "ROLLOVER_OPEN": 3,
    "ROLLOVER_CLOSE": 5,
    "FORCED_EXIT": 5,
}

MAX_SLIPPAGE_PCT_BY_CLASS: Dict[str, float] = {
    "ENTRY": 0.02,
    "EXIT": 0.05,
    "ROLLOVER_OPEN": 0.02,
    "ROLLOVER_CLOSE": 0.05,
    "FORCED_EXIT": 0.05,
}


# ----- Amendment G — Circuit breaker ----------------------------------------

CIRCUIT_THRESHOLDS: Dict[str, float] = {
    "consecutive_abandoned": 2,
    "abandoned_rate_min_n": 5,
    "abandoned_rate_pct": 0.4,
    "rejected_rate_pct": 0.5,
    "late_trade_count": 3,
}


# ----- Amendment B — Kill-at-band-edge --------------------------------------

KILL_BAND_FRACTION: float = 0.85         # 85% of the way to the band
DAILY_BAND_SAFETY_MARGIN: float = 0.01   # 1% inside the band


# ----- Layer 4 — Splitter ---------------------------------------------------

MIN_PARTIAL_FILL_FRACTION: float = 0.5   # threshold for sequential-with-confirm
