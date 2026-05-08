"""Order-routing policy constants.

Single source of truth for tunable order-placement knobs.

Calibration history:
- 2026-05-07: initial values from order-routing redesign (defensive
  defaults, not data-driven).
- 2026-05-08 followup F5: tightened slippage caps + circuit breaker
  rates after edge analysis showed original 2%/5% caps exceeded typical
  per-trade strategy edge (~0.15-0.25%) by ~10x. New values aim for the
  cap to be ≤ 1× typical edge for ENTRY and ≤ 4× ATR for EXIT.

Rationale for ``BUFFER_TICKS_BY_ATTEMPT[1] = 4``:
    Yesterday's al_s1 ENTRY_SHORT bug (2026-05-06 21:00:07) submitted
    FIX_PRICE @ bid1=24645 with zero buffer. The market moved through
    24645 within seconds and never returned. A 4-tick buffer (20 CNY for
    al, price_tick=5) keeps the order marketable for the first ~60s of
    the night session.

Buffer / slippage-cap interaction:
    The cumulative-drift slippage cap (``MAX_SLIPPAGE_PCT_BY_CLASS``)
    is pinned to the strategy-decision price across the whole retry
    chain. Each retry's buffer counts toward the cap. The cap clips
    the chain when ``buffer_ticks_at_attempt_N * price_tick / price``
    exceeds the cap. With the current buffer ladder {1: 4, 2: 8, 3: 16}
    and ENTRY cap of 0.20%:

      | slot       | att-1 % | att-2 % | att-3 % | clipped at |
      | al @ 24600 | 0.020% | 0.041% | 0.081% | full 3 attempts |
      | cu @ 80000 | 0.013% | 0.025% | 0.050% | full 3 attempts |
      | zn @ 22000 | 0.045% | 0.091% | 0.182% | att-3 trips on minor drift |

    For zn, attempt 3's buffer alone (0.182%) leaves only 18 ticks of
    drift headroom; in practice attempt 3 will frequently abandon for
    zn under any adverse market drift. That's intended: if 12 ticks of
    cumulative buffer over 60 seconds don't fill, the market has moved
    enough that not entering is the right call.
"""

from typing import Dict


# ----- Layer 1 — Tick buffer ------------------------------------------------

BUFFER_TICKS_BY_ATTEMPT: Dict[int, int] = {1: 4, 2: 8, 3: 16}
DEFAULT_BUFFER_TICKS: int = 4


# ----- Layer 2 — Watchdog timing --------------------------------------------

WATCHDOG_TICK_S: float = 0.1            # main loop polling cadence
QUIESCENCE_WINDOW_S: float = 1.5        # WINDING_DOWN -> TERMINAL after this gap
DEADLINE_DEFAULT_S: float = 30.0        # cancel-and-resubmit after this idle
TICK_SNAPSHOT_MAX_AGE_S: float = 4.0    # tick freshness threshold (was 2.0; off-peak ticks routinely 3-5s old on SHFE)


# ----- Layer 2 — Resubmit policy by recovery class --------------------------

MAX_ATTEMPTS_BY_CLASS: Dict[str, int] = {
    "ENTRY": 3,
    "EXIT": 5,
    "ROLLOVER_OPEN": 3,
    "ROLLOVER_CLOSE": 5,
    "FORCED_EXIT": 5,
}

# Cumulative-drift slippage cap per recovery class. Pinned to
# intended_price across the entire retry chain (Amendment E). When this
# cap is exceeded by a candidate resubmit price, the chain abandons
# rather than chasing.
#
# Tuning principle: cap ≤ 1× typical per-trade strategy edge for ENTRY,
# ≤ 4× daily ATR for EXIT (Amendment B's kill-at-band-edge handles
# trapped positions in cycle 3+, so EXIT cap need not be wide).
#
# 2026-05-08 followup F5: lowered from {ENTRY: 0.02, EXIT: 0.05, ...}
# which exceeded typical strategy edge of 0.15-0.25% by ~10x.
MAX_SLIPPAGE_PCT_BY_CLASS: Dict[str, float] = {
    "ENTRY": 0.0020,         # was 0.02; ~49 CNY for al @ 24600 = ~10 ticks
    "EXIT": 0.0080,          # was 0.05; relies on Amendment B for trapped
    "ROLLOVER_OPEN": 0.0020, # was 0.02
    "ROLLOVER_CLOSE": 0.0080,# was 0.05
    "FORCED_EXIT": 0.0150,   # was 0.05; widest because already-forced
}


# ----- Amendment G — Circuit breaker ----------------------------------------

# Per-cycle execution-quality thresholds. Tripping the circuit refuses
# new submissions until operator reset.
#
# 2026-05-08 followup F5: tightened from {abandoned_pct: 0.4,
# rejected_pct: 0.5, min_n: 5}. A 40% abandon or 50% rejection rate is
# already a catastrophe by the time it trips — the new values fire
# earlier, leaving margin for operator triage before more capital is
# committed to a broken pipe.
CIRCUIT_THRESHOLDS: Dict[str, float] = {
    "consecutive_abandoned": 2,
    "abandoned_rate_min_n": 10,    # was 5; more stable rate against small-sample noise
    "abandoned_rate_pct": 0.20,    # was 0.4; 20% abandon rate is alarming
    "rejected_rate_pct": 0.25,     # was 0.5; 25% rejection rate is clearly broken
    "late_trade_count": 3,
}


# ----- Amendment B — Kill-at-band-edge --------------------------------------

KILL_BAND_FRACTION: float = 0.85         # 85% of the way to the band
DAILY_BAND_SAFETY_MARGIN: float = 0.01   # 1% inside the band


# ----- Layer 4 — Splitter ---------------------------------------------------

MIN_PARTIAL_FILL_FRACTION: float = 0.5   # threshold for sequential-with-confirm
