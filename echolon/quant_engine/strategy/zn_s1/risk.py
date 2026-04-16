"""
Risk Manager Component - Recoverable Drawdown Circuit Breaker with Regime-Calibrated Recovery
==============================================================================================

Portfolio-level risk management with recoverable equity drawdown
circuit breaker for SHFE zinc futures on daily bars.

Risk Controls:
1. **Drawdown Circuit Breaker (Recoverable State Machine)**:
   - HALT all trading when portfolio equity drawdown from peak
     >= max_drawdown_pct (15.0%). On halt trigger: set is_halted = True,
     block new entries, and flatten existing positions immediately
     (force_exit=True in output).
   - States: ACTIVE (normal trading) and HALTED (entry blocked,
     forced exit signalled, recovery monitoring active).
   - Recovery: After bars_in_halt_state >= regime-specific observation window
     AND current_drawdown_pct <= (max_drawdown_pct - regime-specific buffer),
     reset counters and resume ACTIVE state.

2. **Regime-Calibrated Recovery Windows**:
   - ranging: Standard recovery_observation_window_bars (default 32)
     and recovery_drawdown_buffer_pct (default 2.31%).
   - trending_up: Moderately extended recovery_observation_window_bars_trending_up
     (default 39) and elevated recovery_drawdown_buffer_pct_trending_up
     (default 3.33%) to prevent premature re-entry after profit-capture episodes.
   - trending_down: Extended recovery_observation_window_bars_trending_down
     (default 74) and calibrated recovery_drawdown_buffer_pct_trending_down
     (default 2.13%) for tail vol protection.
   - volatile: Moderate recovery_observation_window_bars_volatile (default 38)
     and calibrated recovery_drawdown_buffer_pct_volatile (default 3.31%)
     for choppiness protection.

3. **Position Limit**: Maximum 1 concurrent position (single-position
   baseline). When at limit, trading_allowed remains True to permit
   exit management, but new entries are blocked by the strategy
   coordinator.

4. **Capital Deployment Limit**: Maximum 100% of total capital may be
   deployed to a single position.

Drawdown Calculation:
    current_drawdown_pct = (peak_equity - current_equity) / peak_equity * 100

Regime Override: Universal 15% halt; regime-specific recovery for
    trending_up, trending_down and volatile regimes.

Indicators: market_regime (Tier 3, via get_market_regime()) for
    regime-specific recovery parameter selection.
"""

from ...core.base.base_component import BaseComponent
from ...core.interfaces.trading_interfaces import ITradingEngine
from ...types import RiskOutput


class risk_manager(BaseComponent):
    """
    Risk manager implementing recoverable drawdown circuit breaker with
    regime-calibrated recovery windows.

    Risk Controls:
        - 15% max drawdown from peak equity (HALT on breach, recoverable;
          force_exit=True signalled on trigger bar to flatten existing positions)
        - Regime-specific recovery:
          trending_up gets moderately extended window (39 bars) and
          elevated buffer (3.33%) to counter profit-capture episodes;
          trending_down gets extended window (74 bars) and calibrated
          buffer (2.13%); volatile gets moderate window (38 bars) and
          buffer (3.31%); ranging uses default window (32 bars) and
          buffer (2.31%)
        - Max 1 concurrent position
        - Max 100% capital deployment per trade

    Parameters (from strategy_params.py RiskParameters):
        - max_drawdown_pct: Maximum drawdown threshold (fixed 15.0%)
        - max_concurrent_positions: Position limit (fixed 1)
        - max_capital_per_trade_pct: Max capital per single position (fixed 100.0%)
        - recovery_observation_window_bars: Standard recovery window (ranging/default, default 32)
        - recovery_drawdown_buffer_pct: Standard recovery buffer (ranging/default, default 2.31%)
        - recovery_observation_window_bars_trending_up: Extended window for trending_up (default 39)
        - recovery_drawdown_buffer_pct_trending_up: Elevated buffer for trending_up (default 3.33%)
        - recovery_observation_window_bars_trending_down: Extended window for trending_down (default 74)
        - recovery_drawdown_buffer_pct_trending_down: Calibrated buffer for trending_down (default 2.13%)
        - recovery_observation_window_bars_volatile: Moderate window for volatile (default 38)
        - recovery_drawdown_buffer_pct_volatile: Calibrated buffer for volatile (default 3.31%)
    """

    def __init__(self, trading_engine: ITradingEngine, **params):
        super().__init__(trading_engine, **params)

        # Extract parameters - direct access, no defaults (no-error-handling policy)
        self.max_drawdown_pct = self.params['max_drawdown_pct']
        self.max_concurrent_positions = self.params['max_concurrent_positions']
        self.max_capital_per_trade_pct = self.params['max_capital_per_trade_pct']

        # Standard recovery params (ranging / default fallback)
        self.recovery_observation_window_bars = self.params['recovery_observation_window_bars']
        self.recovery_drawdown_buffer_pct = self.params['recovery_drawdown_buffer_pct']

        # Regime-specific recovery params: trending_up (moderately extended)
        self.recovery_observation_window_bars_trending_up = self.params['recovery_observation_window_bars_trending_up']
        self.recovery_drawdown_buffer_pct_trending_up = self.params['recovery_drawdown_buffer_pct_trending_up']

        # Regime-specific recovery params: trending_down (extended)
        self.recovery_observation_window_bars_trending_down = self.params['recovery_observation_window_bars_trending_down']
        self.recovery_drawdown_buffer_pct_trending_down = self.params['recovery_drawdown_buffer_pct_trending_down']

        # Regime-specific recovery params: volatile (moderate)
        self.recovery_observation_window_bars_volatile = self.params['recovery_observation_window_bars_volatile']
        self.recovery_drawdown_buffer_pct_volatile = self.params['recovery_drawdown_buffer_pct_volatile']

        # State: track equity high-water mark, halt status, and recovery counter
        # These are cross-trade state - persist across trades, never reset
        self.peak_equity = None
        self.is_halted = False
        self.bars_in_halt_state = 0

    def _get_regime_recovery_params(self, regime: str) -> tuple:
        """
        Select regime-specific recovery parameters.

        Parameters
        ----------
        regime : str
            Current market regime from get_market_regime()

        Returns
        -------
        tuple
            (observation_window_bars, drawdown_buffer_pct) for the current regime
        """
        if regime == 'trending_down':
            return (
                self.recovery_observation_window_bars_trending_down,
                self.recovery_drawdown_buffer_pct_trending_down
            )
        elif regime == 'volatile':
            return (
                self.recovery_observation_window_bars_volatile,
                self.recovery_drawdown_buffer_pct_volatile
            )
        elif regime == 'trending_up':
            return (
                self.recovery_observation_window_bars_trending_up,
                self.recovery_drawdown_buffer_pct_trending_up
            )
        else:
            # Standard params for ranging and any other regime
            return (
                self.recovery_observation_window_bars,
                self.recovery_drawdown_buffer_pct
            )

    def can_trade(self) -> RiskOutput:
        """
        Evaluate risk constraints and determine if trading is allowed.

        Implements a Recoverable State Machine with regime-calibrated recovery:
        - ACTIVE: Normal trading, entry generation enabled
        - HALTED: Entry blocked, recovery monitoring active with
          regime-specific observation windows and drawdown buffers

        Risk checks (in priority order):
        1. Halt state with regime-specific recovery monitoring
        2. Drawdown from peak equity vs max_drawdown_pct threshold
        3. Position count vs max_concurrent_positions

        Returns:
            RiskOutput with trading_allowed and risk_reason fields,
            plus diagnostic extras: current_drawdown_pct, peak_equity,
            current_equity, is_halted, bars_in_halt_state, regime,
            active_recovery_window, active_recovery_buffer.
        """

        # Retrieve current market regime (Tier 3 - interday method)
        regime = self.get_market_regime()

        # =====================================================================
        # Check 1: If halted, monitor for recovery
        # =====================================================================
        if self.is_halted:
            current_equity = self.portfolio.get_total_value()

            # Update high-water mark even during halt
            if current_equity > self.peak_equity:
                self.peak_equity = current_equity

            current_drawdown_pct = self._calculate_drawdown(current_equity)
            self.bars_in_halt_state += 1

            # Select regime-specific recovery parameters
            active_recovery_window, active_recovery_buffer = self._get_regime_recovery_params(regime)
            recovery_threshold = self.max_drawdown_pct - active_recovery_buffer

            # Recovery conditions: BOTH must be met
            time_condition_met = self.bars_in_halt_state >= active_recovery_window
            drawdown_condition_met = current_drawdown_pct <= recovery_threshold

            if time_condition_met and drawdown_condition_met:
                # Recovery: reset counters, set state to ACTIVE
                self.is_halted = False
                self.bars_in_halt_state = 0

                self.log(
                    f"CIRCUIT BREAKER RECOVERED: Drawdown {current_drawdown_pct:.2f}% "
                    f"<= recovery threshold {recovery_threshold:.1f}% after "
                    f"{active_recovery_window} bars observation "
                    f"(regime={regime}). Trading RESUMED.",
                    "warning"
                )

                output = RiskOutput(
                    trading_allowed=True,
                    risk_reason=(
                        f"RECOVERED from halt. Drawdown {current_drawdown_pct:.2f}% "
                        f"<= {recovery_threshold:.1f}% recovery threshold "
                        f"(regime={regime}, window={active_recovery_window}, "
                        f"buffer={active_recovery_buffer:.1f}%). "
                        f"Trading resumed."
                    ),
                    current_drawdown_pct=current_drawdown_pct,
                    peak_equity=self.peak_equity,
                    current_equity=current_equity,
                    is_halted=False,
                    bars_in_halt_state=0,
                    regime=regime,
                    active_recovery_window=active_recovery_window,
                    active_recovery_buffer=active_recovery_buffer
                )
                self.log_risk_output(output)
                return output

            # Still halted - report recovery progress
            bars_remaining = max(0, active_recovery_window - self.bars_in_halt_state)

            output = RiskOutput(
                trading_allowed=False,
                risk_reason=(
                    f"CIRCUIT BREAKER ACTIVE: Drawdown {current_drawdown_pct:.2f}% "
                    f"(recovery requires <= {recovery_threshold:.1f}%). "
                    f"Bars in halt: {self.bars_in_halt_state}/"
                    f"{active_recovery_window} "
                    f"(time met: {time_condition_met}, dd met: {drawdown_condition_met}). "
                    f"Regime={regime}, bars remaining={bars_remaining}."
                ),
                current_drawdown_pct=current_drawdown_pct,
                peak_equity=self.peak_equity,
                current_equity=current_equity,
                is_halted=True,
                bars_in_halt_state=self.bars_in_halt_state,
                regime=regime,
                active_recovery_window=active_recovery_window,
                active_recovery_buffer=active_recovery_buffer
            )
            self.log_risk_output(output)
            return output

        # =====================================================================
        # Check 2: Drawdown circuit breaker
        # =====================================================================
        current_equity = self.portfolio.get_total_value()

        # Initialize peak equity on first call
        if self.peak_equity is None:
            self.peak_equity = current_equity

        # Update high-water mark
        if current_equity > self.peak_equity:
            self.peak_equity = current_equity

        current_drawdown_pct = self._calculate_drawdown(current_equity)

        if current_drawdown_pct >= self.max_drawdown_pct:
            # Trigger circuit breaker - enter HALTED state
            self.is_halted = True
            self.bars_in_halt_state = 0

            # Get regime-specific recovery params for reporting
            active_recovery_window, active_recovery_buffer = self._get_regime_recovery_params(regime)
            recovery_threshold = self.max_drawdown_pct - active_recovery_buffer

            self.log(
                f"CIRCUIT BREAKER TRIGGERED: Drawdown {current_drawdown_pct:.2f}% "
                f">= limit {self.max_drawdown_pct:.1f}%. "
                f"Peak equity: {self.peak_equity:.2f}, "
                f"Current equity: {current_equity:.2f}. "
                f"Trading HALTED. Recovery requires {active_recovery_window} bars "
                f"and drawdown <= {recovery_threshold:.1f}% "
                f"(regime={regime}).",
                "warning"
            )

            output = RiskOutput(
                trading_allowed=False,
                risk_reason=(
                    f"CIRCUIT BREAKER TRIGGERED: Drawdown {current_drawdown_pct:.2f}% "
                    f">= {self.max_drawdown_pct:.1f}% limit. "
                    f"Peak: {self.peak_equity:.2f}, Current: {current_equity:.2f}. "
                    f"Trading halted. Flattening existing positions immediately. "
                    f"Recovery monitoring started "
                    f"(regime={regime}, window={active_recovery_window}, "
                    f"buffer={active_recovery_buffer:.1f}%)."
                ),
                current_drawdown_pct=current_drawdown_pct,
                peak_equity=self.peak_equity,
                current_equity=current_equity,
                is_halted=True,
                bars_in_halt_state=0,
                regime=regime,
                active_recovery_window=active_recovery_window,
                active_recovery_buffer=active_recovery_buffer,
                force_exit=True
            )
            self.log_risk_output(output)
            return output

        # =====================================================================
        # Check 3: Position limit
        # =====================================================================
        position = self.portfolio.get_position()
        has_position = position is not None and position.size != 0
        current_position_count = 1 if has_position else 0

        if current_position_count >= self.max_concurrent_positions:
            # Position limit reached - still allow trading for exit management
            output = RiskOutput(
                trading_allowed=True,
                risk_reason=(
                    f"Position limit reached ({current_position_count}/"
                    f"{self.max_concurrent_positions}). "
                    f"Drawdown: {current_drawdown_pct:.2f}%. "
                    f"Existing position active - exits still allowed."
                ),
                current_drawdown_pct=current_drawdown_pct,
                peak_equity=self.peak_equity,
                current_equity=current_equity,
                is_halted=False,
                bars_in_halt_state=0,
                regime=regime
            )
            self.log_risk_output(output)
            return output

        # =====================================================================
        # All checks passed - trading allowed
        # =====================================================================
        output = RiskOutput(
            trading_allowed=True,
            risk_reason=(
                f"Trading allowed. Drawdown: {current_drawdown_pct:.2f}% "
                f"(limit: {self.max_drawdown_pct:.1f}%). "
                f"Positions: {current_position_count}/{self.max_concurrent_positions}. "
                f"Regime: {regime}."
            ),
            current_drawdown_pct=current_drawdown_pct,
            peak_equity=self.peak_equity,
            current_equity=current_equity,
            is_halted=False,
            bars_in_halt_state=0,
            regime=regime
        )
        self.log_risk_output(output)
        return output

    def _calculate_drawdown(self, current_equity: float) -> float:
        """
        Calculate current drawdown percentage from peak equity.

        Formula: (peak_equity - current_equity) / peak_equity * 100

        Parameters
        ----------
        current_equity : float
            Current portfolio equity value

        Returns
        -------
        float
            Current drawdown as a positive percentage (0.0 = no drawdown)
        """
        if self.peak_equity <= 0:
            return 0.0

        drawdown_pct = (self.peak_equity - current_equity) / self.peak_equity * 100.0

        # Drawdown is always non-negative (when equity is at or above peak, DD = 0)
        if drawdown_pct < 0.0:
            return 0.0

        return drawdown_pct

    def _get_component_specific_state(self):
        """Return risk-specific state for live trading persistence."""
        return {
            'peak_equity': self.peak_equity,
            'is_halted': self.is_halted,
            'bars_in_halt_state': self.bars_in_halt_state
        }

    def _restore_component_specific_state(self, state):
        """Restore risk-specific state from persistence."""
        self.peak_equity = state['peak_equity']
        self.is_halted = state['is_halted']
        self.bars_in_halt_state = state['bars_in_halt_state']
