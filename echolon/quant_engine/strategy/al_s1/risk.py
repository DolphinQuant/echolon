"""
Risk Manager Component - Drawdown Circuit Breaker
==================================================

Portfolio-level risk management with drawdown circuit breaker.
Applies universally across all market regimes (trending_up, trending_down,
ranging, volatile).

Risk Controls:
1. **Drawdown Circuit Breaker**: HALT all trading when drawdown from equity
   high-water mark >= max_drawdown_pct (15.0% fixed). Once triggered,
   trading remains halted permanently (manual restart required in live
   trading). Strategy coordinator flattens open positions on halt.

2. **Position Limit**: Maximum 1 concurrent position. When at limit,
   trading_allowed remains True to permit exit management, but new entries
   are blocked by the strategy coordinator.

Drawdown Calculation:
    current_drawdown_pct = (peak_equity - current_equity) / peak_equity * 100

No indicators are required - risk checks are purely portfolio-based.
"""

from ...core.base.base_component import BaseComponent
from ...core.interfaces.trading_interfaces import ITradingEngine
from ...types import RiskOutput


class risk_manager(BaseComponent):
    """
    Risk manager implementing drawdown circuit breaker and position limits.

    Risk Controls:
        - 15% max drawdown from peak equity (HALT_ALL on breach)
        - Max 1 concurrent position

    Parameters (from strategy_params.py RiskParameters):
        - max_drawdown_pct: Maximum drawdown threshold (fixed 15.0%)
        - max_concurrent_positions: Position limit (fixed 1)
    """

    def __init__(self, trading_engine: ITradingEngine, frequency_context=None,
                 market_adapter=None, **params):
        super().__init__(trading_engine, frequency_context, market_adapter, **params)

        # Extract parameters - direct access, no defaults (no-error-handling policy)
        self.max_drawdown_pct = self.params['max_drawdown_pct']
        self.max_concurrent_positions = self.params['max_concurrent_positions']

        # State: track equity high-water mark and halt status
        self.peak_equity = None
        self.is_halted = False

    def can_trade(self) -> RiskOutput:
        """
        Evaluate risk constraints and determine if trading is allowed.

        Risk checks (in priority order):
        1. Circuit breaker halt state (previously triggered)
        2. Drawdown from peak equity vs max_drawdown_pct threshold
        3. Position count vs max_concurrent_positions

        Returns:
            RiskOutput with trading_allowed and risk_reason fields,
            plus diagnostic extras: current_drawdown_pct, peak_equity,
            current_equity, is_halted.
        """

        # =====================================================================
        # Check 1: If previously halted, remain halted permanently
        # =====================================================================
        if self.is_halted:
            current_equity = self.portfolio.get_total_value()
            current_drawdown_pct = self._calculate_drawdown(current_equity)

            output = RiskOutput(
                trading_allowed=False,
                risk_reason=(
                    f"CIRCUIT BREAKER ACTIVE: Trading halted permanently. "
                    f"Drawdown {current_drawdown_pct:.2f}% from peak "
                    f"{self.peak_equity:.2f}. Manual restart required."
                ),
                current_drawdown_pct=current_drawdown_pct,
                peak_equity=self.peak_equity,
                current_equity=current_equity,
                is_halted=True
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
            # Trigger circuit breaker - permanent halt
            self.is_halted = True

            self.log(
                f"CIRCUIT BREAKER TRIGGERED: Drawdown {current_drawdown_pct:.2f}% "
                f">= limit {self.max_drawdown_pct:.1f}%. "
                f"Peak equity: {self.peak_equity:.2f}, "
                f"Current equity: {current_equity:.2f}. "
                f"ALL TRADING HALTED.",
                "warning"
            )

            output = RiskOutput(
                trading_allowed=False,
                risk_reason=(
                    f"CIRCUIT BREAKER TRIGGERED: Drawdown {current_drawdown_pct:.2f}% "
                    f">= {self.max_drawdown_pct:.1f}% limit. "
                    f"Peak: {self.peak_equity:.2f}, Current: {current_equity:.2f}. "
                    f"Trading halted."
                ),
                current_drawdown_pct=current_drawdown_pct,
                peak_equity=self.peak_equity,
                current_equity=current_equity,
                is_halted=True
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
            # but log diagnostic info about position state
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
                is_halted=False
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
                f"Positions: {current_position_count}/{self.max_concurrent_positions}."
            ),
            current_drawdown_pct=current_drawdown_pct,
            peak_equity=self.peak_equity,
            current_equity=current_equity,
            is_halted=False
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
            'is_halted': self.is_halted
        }

    def _restore_component_specific_state(self, state):
        """Restore risk-specific state from persistence."""
        self.peak_equity = state['peak_equity']
        self.is_halted = state['is_halted']
