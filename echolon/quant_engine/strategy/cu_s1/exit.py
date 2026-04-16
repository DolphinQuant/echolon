"""
Exit Component - Eight-Pathway Cascade Momentum Strategy

Business Logic Source: workspace/current/strategy/exit_prompt.md

Strategy: ATR-based trailing stop ratchet (regime-specific) with additive profit-protection
  floor and time-based safety backstop.
  Eight cascade pathways:
    Pathway 1 (ranging LONG):         trailing_stop = max(rolling_high_5d - 4.0×ATR(period), prior_stop)
                                      time_exit: bars_in_position >= max_holding_period_ranging (25)
    Pathway 2 (trending_up LONG):     trailing_stop = max(rolling_high_5d - 3.5×ATR(period), prior_stop)
                                      time_exit: bars_in_position >= max_holding_period_trending_up (20)
    Pathway 3 (trending_down SHORT):  trailing_stop = min(rolling_low_5d + 3.5×ATR(period), prior_stop)
                                      time_exit: bars_in_position >= max_holding_period_trending_down (20)
    Pathway 4 (volatile LONG):        trailing_stop = max(rolling_high_5d - 4.0×ATR(period), prior_stop)
                                      time_exit: bars_in_position >= max_holding_period_volatile (18)
    Pathway 5 (trending_down LONG):   trailing_stop = max(rolling_high_5d - 3.5×ATR(period), prior_stop)
                                      time_exit: bars_in_position >= max_holding_period_trending_down (20)
                                      Inherits trending_down parameters (universal coverage)
    Pathway 6 (trending_up SHORT):    trailing_stop = min(rolling_low_5d + 3.5×ATR(period), prior_stop)
                                      time_exit: bars_in_position >= max_holding_period_trending_up_short (15)
                                      CASCADE: inherits trending_down SHORT template (separate optimizable params)
    Pathway 7 (volatile SHORT):       trailing_stop = min(rolling_low_5d + 4.0×ATR(period), prior_stop)
                                      time_exit: bars_in_position >= max_holding_period_volatile (18)
                                      CASCADE: inherits volatile_LONG params exactly
    Pathway 8 (ranging SHORT):        trailing_stop = min(rolling_low_5d + 4.0×ATR(period), prior_stop)
                                      time_exit: bars_in_position >= max_holding_period_ranging (25)
                                      CASCADE: inherits ranging_LONG params exactly

  - LONG stop ratchets upward only (never decreases)
  - SHORT stop ratchets downward only (never increases)
  - Pathway determined at trade entry via market_regime + direction and locked for trade duration

Profit Protection Floor (additive mechanism, Priority 2):
  - Activation trigger: unrealized_pnl >= profit_protection_activation_r_multiple × initial_stop_distance
  - Floor (LONG): best_price_seen - profit_protection_floor_atr_multiple × ATR
  - Floor (SHORT): best_price_seen + profit_protection_floor_atr_multiple × ATR
  - Once activated (profit_floor_active latches True), floor is evaluated at Priority 2 before trailing stop
  - best_price_seen tracks max daily high (LONG) or min daily low (SHORT)

Exit Execution Priority (BUG_002 fix: floor promoted to Priority 1):
  Priority 1: Profit protection floor breach (when profit_floor_active=True)
              Evaluated first to prevent trailing stop from consuming floor gains
  Priority 2: Time-based exit IF bars_in_position >= max_holding_period
  Priority 3: Trailing stop breach (LONG: price <= stop, SHORT: price >= stop)
  Forced: Contract expiry via ForcedExitStrategyHook (handled automatically)

Indicator Tiers:
  - atr_{atr_period} : Tier 1 (with lookback period, e.g., atr_20)
  - market_regime    : Tier 3 (bare name via get_market_regime())

State Variables (per-trade, persisted for live trading):
  - trailing_stop           : Current trailing stop price level (None before first bar with position)
  - bars_in_position        : Number of bars held in current position
  - recent_highs            : Rolling list of up to rolling_high_window bar highs (LONG)
  - recent_lows             : Rolling list of up to rolling_low_window bar lows (SHORT)
  - active_pathway_regime   : Regime+direction key locked at trade entry for parameter dispatch
                              Values: 'ranging', 'trending_up', 'trending_down',
                                      'volatile', 'trending_up_short'
  - initial_stop_distance   : ATR×multiplier locked at entry bar (denominator for 2R check)
  - best_price_seen         : Most favorable price seen (LONG: max high; SHORT: min low)
  - profit_floor_active     : Whether profit protection floor is latched on (True once 2R crossed)
"""

from typing import Any, Dict, List, Optional

from ...core.base.base_component import BaseComponent
from ...core.interfaces.trading_interfaces import ITradingEngine
from ...types import ExitSignalOutput, OrderIntent


class exit_rule(BaseComponent):
    """
    Regime-specific ATR trailing stop exit with additive profit-protection floor and time backstop.

    Implements eight cascade exit pathways for the multi-regime momentum strategy:
      - ranging LONG:        ratchet-up trailing stop from rolling 5-day high (4.0× ATR)
      - trending_up LONG:    ratchet-up trailing stop from rolling 5-day high (3.5× ATR)
      - trending_down SHORT: ratchet-down trailing stop from rolling 5-day low (3.5× ATR)
      - volatile LONG:       ratchet-up trailing stop from rolling 5-day high (4.0× ATR)
      - trending_down LONG:  ratchet-up trailing stop from rolling 5-day high (3.5× ATR, universal coverage)
      - trending_up SHORT:   ratchet-down trailing stop from rolling 5-day low (3.5× ATR, CASCADE)
      - volatile SHORT:      ratchet-down trailing stop from rolling 5-day low (4.0× ATR, CASCADE)
      - ranging SHORT:       ratchet-down trailing stop from rolling 5-day low (4.0× ATR, CASCADE)

    Additive profit-protection floor activates at 2R unrealized profit, anchoring a dynamic
    floor at best_price_seen - floor_atr_multiple×ATR. Once triggered, evaluated at Priority 2
    before the trailing stop to prevent giving back excessive gains.

    ATR multipliers and holding periods are regime-calibrated. The active pathway
    is locked at trade entry (first bar with position) to prevent mid-trade parameter
    drift if the market regime transitions.
    """

    def __init__(self, trading_engine: ITradingEngine, **params):
        super().__init__(trading_engine, **params)

        # --- Calculation parameters (Tier 1 indicator period, shared across pathways) ---
        self.atr_period: int = self.params['atr_period']

        # --- Regime-specific ATR multipliers ---
        self.atr_multiplier_ranging: float = self.params['atr_multiplier_ranging']
        self.atr_multiplier_trending_up: float = self.params['atr_multiplier_trending_up']
        self.atr_multiplier_trending_down: float = self.params['atr_multiplier_trending_down']
        self.atr_multiplier_trending_up_short: float = self.params['atr_multiplier_trending_up_short']
        self.atr_multiplier_volatile: float = self.params['atr_multiplier_volatile']

        # --- Regime-specific time backstop periods ---
        self.max_holding_period_ranging: int = self.params['max_holding_period_ranging']
        self.max_holding_period_trending_up: int = self.params['max_holding_period_trending_up']
        self.max_holding_period_trending_down: int = self.params['max_holding_period_trending_down']
        self.max_holding_period_trending_up_short: int = self.params['max_holding_period_trending_up_short']
        self.max_holding_period_volatile: int = self.params['max_holding_period_volatile']

        # --- Rolling window sizes (LONG high vs SHORT low, both FIXED=5) ---
        self.rolling_high_window: int = self.params['rolling_high_window']
        self.rolling_low_window: int = self.params['rolling_low_window']

        # --- Profit protection floor parameters ---
        self.profit_protection_activation_r_multiple: float = self.params['profit_protection_activation_r_multiple']
        self.profit_protection_floor_atr_multiple: float = self.params['profit_protection_floor_atr_multiple']

        # --- Pathway direction/regime configuration (7 regimes, 8 pathways) ---
        self.exit_direction_regime_1: str = self.params['exit_direction_regime_1']
        self.exit_direction_regime_2: str = self.params['exit_direction_regime_2']
        self.exit_direction_regime_3: str = self.params['exit_direction_regime_3']
        self.exit_direction_regime_4: str = self.params['exit_direction_regime_4']
        self.exit_direction_regime_5: str = self.params['exit_direction_regime_5']
        self.exit_direction_regime_6: str = self.params['exit_direction_regime_6']
        self.exit_direction_regime_7: str = self.params['exit_direction_regime_7']

        # --- Per-trade state variables ---
        self.trailing_stop: Optional[float] = None
        self.bars_in_position: int = 0
        self.recent_highs: List[float] = []   # Rolling window of bar highs (LONG pathway)
        self.recent_lows: List[float] = []    # Rolling window of bar lows (SHORT pathway)
        self.active_pathway_regime: Optional[str] = None  # Locked at entry bar
        self.initial_stop_distance: Optional[float] = None  # ATR×multiplier at entry (for 2R check)
        self.best_price_seen: Optional[float] = None  # Max high (LONG) / min low (SHORT)
        self.profit_floor_active: bool = False  # Latched True when 2R threshold crossed

        self.log(
            f"exit_rule init: atr_period={self.atr_period}, "
            f"atr_multiplier_ranging={self.atr_multiplier_ranging}, "
            f"atr_multiplier_trending_up={self.atr_multiplier_trending_up}, "
            f"atr_multiplier_trending_down={self.atr_multiplier_trending_down}, "
            f"atr_multiplier_trending_up_short={self.atr_multiplier_trending_up_short}, "
            f"atr_multiplier_volatile={self.atr_multiplier_volatile}, "
            f"max_holding_period_ranging={self.max_holding_period_ranging}, "
            f"max_holding_period_trending_up={self.max_holding_period_trending_up}, "
            f"max_holding_period_trending_down={self.max_holding_period_trending_down}, "
            f"max_holding_period_trending_up_short={self.max_holding_period_trending_up_short}, "
            f"max_holding_period_volatile={self.max_holding_period_volatile}, "
            f"rolling_high_window={self.rolling_high_window}, "
            f"rolling_low_window={self.rolling_low_window}, "
            f"profit_protection_activation_r_multiple={self.profit_protection_activation_r_multiple}, "
            f"profit_protection_floor_atr_multiple={self.profit_protection_floor_atr_multiple}"
        )

    # ------------------------------------------------------------------
    # State Management Trio (required for live trading persistence)
    # ------------------------------------------------------------------

    def _get_component_specific_state(self) -> Dict[str, Any]:
        """Return per-trade state dict for live trading persistence."""
        return {
            'trailing_stop': self.trailing_stop,
            'bars_in_position': self.bars_in_position,
            'recent_highs': list(self.recent_highs),
            'recent_lows': list(self.recent_lows),
            'active_pathway_regime': self.active_pathway_regime,
            'initial_stop_distance': self.initial_stop_distance,
            'best_price_seen': self.best_price_seen,
            'profit_floor_active': self.profit_floor_active,
        }

    def _restore_component_specific_state(self, state: Dict[str, Any]) -> None:
        """Restore per-trade state from persistence dict."""
        self.trailing_stop = state['trailing_stop']
        self.bars_in_position = state['bars_in_position']
        self.recent_highs = list(state['recent_highs'])
        self.recent_lows = list(state['recent_lows'])
        self.active_pathway_regime = state['active_pathway_regime']
        self.initial_stop_distance = state['initial_stop_distance']
        self.best_price_seen = state['best_price_seen']
        self.profit_floor_active = state['profit_floor_active']

    def _reset_state(self) -> None:
        """Reset all per-trade state to initial values (called when no position exists)."""
        self.trailing_stop = None
        self.bars_in_position = 0
        self.recent_highs = []
        self.recent_lows = []
        self.active_pathway_regime = None
        self.initial_stop_distance = None
        self.best_price_seen = None
        self.profit_floor_active = False

    # ------------------------------------------------------------------
    # Main Exit Method
    # ------------------------------------------------------------------

    def should_exit(self) -> ExitSignalOutput:
        """
        Evaluate exit conditions for the current daily bar.

        Pathway dispatch logic (locked at entry, 8 pathways):
          LONG:
            - ranging regime      → 'ranging'          (pathway 1)
            - volatile regime     → 'volatile'          (pathway 4)
            - trending_down regime→ 'trending_down'     (pathway 5, universal coverage)
            - trending_up/other   → 'trending_up'       (pathway 2)
          SHORT:
            - trending_up regime  → 'trending_up_short' (pathway 6, CASCADE)
            - volatile regime     → 'volatile'          (pathway 7, CASCADE — inherits volatile_LONG params)
            - ranging regime      → 'ranging'           (pathway 8, CASCADE — inherits ranging_LONG params)
            - trending_down/other → 'trending_down'     (pathway 3)

        Exit triggers (checked in priority order, BUG_002 fix applied):
          Priority 1. Profit floor       : (profit_floor_active) AND
                                           LONG: current_price <= best_price_seen - floor_atr × ATR
                                           SHORT: current_price >= best_price_seen + floor_atr × ATR
                                           Evaluated first to prevent trailing stop from
                                           consuming floor-protected gains before floor triggers.
          Priority 2. Time backstop      : bars_in_position >= max_holding_period (regime-specific)
          Priority 3. Trailing stop      :
                LONG:  current_price <= trailing_stop
                       trailing_stop = max(trailing_stop, rolling_high_5d - atr_multiplier × ATR)
                SHORT: current_price >= trailing_stop
                       trailing_stop = min(trailing_stop, rolling_low_5d + atr_multiplier × ATR)

        Profit floor activation:
          LONG:  (current_price - entry_price) >= activation_r_multiple × initial_stop_distance
          SHORT: (entry_price - current_price) >= activation_r_multiple × initial_stop_distance
          Once activated, profit_floor_active latches True for remainder of trade.

        On first bar with position, trailing stop initialised at entry price ± atr_multiplier×ATR,
        then candidate from rolling window is merged via ratchet rule.
        initial_stop_distance is locked on the same first bar.

        Returns:
            ExitSignalOutput with should_exit flag, exit_reason, position metadata,
            and diagnostic fields (trailing_stop, rolling_reference, atr_value,
            stop_distance, entry_price, active_regime).
        """
        position = self.portfolio.get_position()

        # --- No position: clean up state and return hold ---
        if position is None or position.size == 0:
            self._reset_state()
            output = ExitSignalOutput(
                should_exit=False,
                exit_reason='No position to exit',
                position_size=0.0,
                bars_since_entry=0,
                intent=None
            )
            self.log_exit_output(output)
            return output

        # --- Increment bar counter ---
        self.bars_in_position += 1

        # --- Gather bar data ---
        current_bar = self.get_current_bar()
        current_price: float = self.get_current_price()
        entry_price: float = position.avg_price
        is_long: bool = position.size > 0

        # --- Lock active pathway regime on first bar of position ---
        if self.active_pathway_regime is None:
            current_regime = self.get_market_regime()
            if is_long:
                if current_regime == 'ranging':
                    self.active_pathway_regime = 'ranging'
                elif current_regime == 'volatile':
                    self.active_pathway_regime = 'volatile'
                elif current_regime == 'trending_down':
                    # trending_down LONG (pathway 5): inherits trending_down params (universal coverage)
                    self.active_pathway_regime = 'trending_down'
                else:
                    # trending_up or unknown LONG → trending_up pathway
                    self.active_pathway_regime = 'trending_up'
            else:
                # SHORT: detect regime for cascade pathway dispatch
                if current_regime == 'trending_up':
                    # trending_up SHORT cascade (pathway 6)
                    self.active_pathway_regime = 'trending_up_short'
                elif current_regime == 'volatile':
                    # volatile SHORT inherits volatile_LONG params exactly (pathway 7, CASCADE)
                    self.active_pathway_regime = 'volatile'
                elif current_regime == 'ranging':
                    # ranging SHORT inherits ranging_LONG params exactly (pathway 8, CASCADE)
                    self.active_pathway_regime = 'ranging'
                else:
                    # trending_down or unknown SHORT → trending_down pathway (pathway 3)
                    self.active_pathway_regime = 'trending_down'

        # --- Resolve pathway parameters ---
        if self.active_pathway_regime == 'ranging':
            atr_multiplier = self.atr_multiplier_ranging
            max_holding_period = self.max_holding_period_ranging
        elif self.active_pathway_regime == 'trending_up':
            atr_multiplier = self.atr_multiplier_trending_up
            max_holding_period = self.max_holding_period_trending_up
        elif self.active_pathway_regime == 'trending_up_short':
            # CASCADE: inherits trending_down SHORT template (separate optimizable params)
            atr_multiplier = self.atr_multiplier_trending_up_short
            max_holding_period = self.max_holding_period_trending_up_short
        elif self.active_pathway_regime == 'volatile':
            # Both volatile LONG (pathway 4) and volatile SHORT (pathway 7) use same params (CASCADE)
            atr_multiplier = self.atr_multiplier_volatile
            max_holding_period = self.max_holding_period_volatile
        else:
            # 'trending_down' — pathway 3 (SHORT) and pathway 5 (LONG, universal coverage)
            atr_multiplier = self.atr_multiplier_trending_down
            max_holding_period = self.max_holding_period_trending_down

        # --- Compute ATR and stop distance ---
        atr: float = self.get_indicator(f'atr_{self.atr_period}')
        stop_distance: float = atr_multiplier * atr

        # --- Compute rolling reference and trailing stop (direction-dependent) ---
        if is_long:
            current_high: float = current_bar['high']
            self.recent_highs.append(current_high)
            if len(self.recent_highs) > self.rolling_high_window:
                self.recent_highs = self.recent_highs[-self.rolling_high_window:]

            rolling_reference: float = max(self.recent_highs)
            candidate_stop: float = rolling_reference - stop_distance

            if self.trailing_stop is None:
                # Initialise: entry price - stop_distance, merged with candidate; lock initial_stop_distance
                initial_stop: float = entry_price - stop_distance
                self.trailing_stop = max(initial_stop, candidate_stop)
                self.initial_stop_distance = stop_distance

            else:
                # Ratchet upward only for LONG
                self.trailing_stop = max(self.trailing_stop, candidate_stop)

        else:
            # SHORT pathway: use rolling low window, ratchet downward
            current_low: float = current_bar['low']
            self.recent_lows.append(current_low)
            if len(self.recent_lows) > self.rolling_low_window:
                self.recent_lows = self.recent_lows[-self.rolling_low_window:]

            rolling_reference = min(self.recent_lows)
            candidate_stop = rolling_reference + stop_distance

            if self.trailing_stop is None:
                # Initialise: entry price + stop_distance, merged with candidate; lock initial_stop_distance
                initial_stop = entry_price + stop_distance
                self.trailing_stop = min(initial_stop, candidate_stop)
                self.initial_stop_distance = stop_distance

            else:
                # Ratchet downward only for SHORT
                self.trailing_stop = min(self.trailing_stop, candidate_stop)

        # --- Update best_price_seen for profit floor tracking ---
        if is_long:
            if self.best_price_seen is None:
                self.best_price_seen = current_bar['high']
            else:
                self.best_price_seen = max(self.best_price_seen, current_bar['high'])
        else:
            if self.best_price_seen is None:
                self.best_price_seen = current_bar['low']
            else:
                self.best_price_seen = min(self.best_price_seen, current_bar['low'])

        # --- Activate profit protection floor latch if 2R threshold crossed ---
        if not self.profit_floor_active:
            if is_long:
                unrealized_pnl_price = current_price - entry_price
            else:
                unrealized_pnl_price = entry_price - current_price
            if unrealized_pnl_price >= self.profit_protection_activation_r_multiple * self.initial_stop_distance:
                self.profit_floor_active = True

        # --- Compute profit floor level (used if active) ---
        if is_long:
            profit_floor_level: float = self.best_price_seen - self.profit_protection_floor_atr_multiple * atr
        else:
            profit_floor_level = self.best_price_seen + self.profit_protection_floor_atr_multiple * atr

        # --- Capture pre-decision snapshots (before potential reset) ---
        trailing_stop_snapshot: float = self.trailing_stop
        bars_snapshot: int = self.bars_in_position
        active_regime_snapshot: str = self.active_pathway_regime

        # --- Evaluate exit conditions ---
        should_exit_flag: bool = False
        intent: Optional[OrderIntent] = None
        reason: str = ''

        # Priority 1: Profit protection floor breach (when activated)
        # Evaluated before time backstop so it can lock in gains when 2R threshold is crossed
        if self.profit_floor_active and is_long and current_price <= profit_floor_level:
            should_exit_flag = True
            intent = OrderIntent.EXIT_LONG
            reason = (
                f'Profit floor (LONG/{active_regime_snapshot}): '
                f'price={current_price:.4f} <= floor={profit_floor_level:.4f} '
                f'(best_price={self.best_price_seen:.4f}, '
                f'atr={atr:.4f}, floor_mult={self.profit_protection_floor_atr_multiple})'
            )

        elif self.profit_floor_active and not is_long and current_price >= profit_floor_level:
            should_exit_flag = True
            intent = OrderIntent.EXIT_SHORT
            reason = (
                f'Profit floor (SHORT/{active_regime_snapshot}): '
                f'price={current_price:.4f} >= floor={profit_floor_level:.4f} '
                f'(best_price={self.best_price_seen:.4f}, '
                f'atr={atr:.4f}, floor_mult={self.profit_protection_floor_atr_multiple})'
            )

        # Priority 2: Time-based backstop
        elif self.bars_in_position >= max_holding_period:
            should_exit_flag = True
            intent = OrderIntent.EXIT_LONG if is_long else OrderIntent.EXIT_SHORT
            reason = (
                f'Time backstop [{active_regime_snapshot}]: '
                f'bars_held={self.bars_in_position} >= '
                f'max_holding_period={max_holding_period}'
            )

        # Priority 3: Trailing stop breach (LONG)
        elif is_long and current_price <= self.trailing_stop:
            should_exit_flag = True
            intent = OrderIntent.EXIT_LONG
            reason = (
                f'Trailing stop (LONG/{active_regime_snapshot}): '
                f'price={current_price:.4f} <= stop={self.trailing_stop:.4f} '
                f'(rolling_high_5d={rolling_reference:.4f}, '
                f'atr={atr:.4f}, multiplier={atr_multiplier})'
            )

        # Priority 3: Trailing stop breach (SHORT)
        elif not is_long and current_price >= self.trailing_stop:
            should_exit_flag = True
            intent = OrderIntent.EXIT_SHORT
            reason = (
                f'Trailing stop (SHORT/{active_regime_snapshot}): '
                f'price={current_price:.4f} >= stop={self.trailing_stop:.4f} '
                f'(rolling_low_5d={rolling_reference:.4f}, '
                f'atr={atr:.4f}, multiplier={atr_multiplier})'
            )

        # No exit: log holding status
        else:
            direction_label = 'LONG' if is_long else 'SHORT'
            floor_status = f', floor_active={self.profit_floor_active}, floor_level={profit_floor_level:.4f}' if self.profit_floor_active else ''
            reason = (
                f'Holding {direction_label} [{active_regime_snapshot}] '
                f'(bar {self.bars_in_position}/{max_holding_period}): '
                f'price={current_price:.4f}, '
                f'trailing_stop={self.trailing_stop:.4f}, '
                f'rolling_ref={rolling_reference:.4f}, '
                f'atr={atr:.4f}, stop_distance={stop_distance:.4f}'
                f'{floor_status}'
            )

        # --- Reset per-trade state if exiting ---
        if should_exit_flag:
            self._reset_state()

        output = ExitSignalOutput(
            should_exit=should_exit_flag,
            exit_reason=reason,
            position_size=abs(position.size),
            bars_since_entry=bars_snapshot,
            intent=intent,
            trailing_stop=trailing_stop_snapshot,
            rolling_reference=rolling_reference,
            atr_value=atr,
            stop_distance=stop_distance,
            entry_price=entry_price,
            active_regime=active_regime_snapshot
        )

        self.log_exit_output(output)
        return output
