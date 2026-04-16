"""
Risk Manager - Eight-Pathway Regime-Aware Momentum Strategy (SHFE Interday)

Business Logic Source: workspace/current/strategy/risk_prompt.md

Risk State Machine:
  - NORMAL  : Full entry permission (no active cooldown)
  - COOLDOWN: Entry prohibited for cooldown_bars_after_loss bars after a losing trade exit
  - HALTED  : Drawdown >= max_drawdown_pct (hard circuit breaker)

Risk Controls (cascade to ALL eight pathways):
  - Drawdown halt (HALTED): Block trading if drawdown from equity peak >= max_drawdown_pct (15%)
  - Position limit: Max 1 concurrent position enforced
  - Loss cooldown (COOLDOWN): Entry prohibited for cooldown_bars_after_loss (3) consecutive bars
    after a losing trade exit; breaks drawdown accumulation clusters without
    level-based threshold sensitivity

Pathways covered (cascade_application per risk_prompt.md):
  - Pathway 1: ranging LONG        via MFI mean-reversion
  - Pathway 2: trending_up LONG    via SAR trend-following + ADX confirmation
  - Pathway 3: trending_down SHORT via OBV continuation
  - Pathway 4: volatile LONG       via ADX breakout
  - Pathway 5: trending_up SHORT   via MINUS_DM exhaustion
  - Pathway 6: volatile SHORT      via ADXR exhaustion
  - Pathway 7: trending_down LONG  via NATR volatility spike counter-trend
  - Pathway 8: ranging SHORT       via WILLR mean-reversion

Parameters (owned):
  - max_drawdown_pct          : float, fixed 15.0 - hard halt threshold from equity peak
  - cooldown_bars_after_loss  : int, fixed 3 - bars of entry prohibition after losing trade
  - max_concurrent_positions  : int, fixed 1 - single position baseline
  - max_capital_deployed_pct  : float, fixed 100.0 - capital deployment per position

State (cross-trade, never reset):
  - equity_high_water_mark  : float - tracks equity peak for drawdown calculation
  - prev_position_size      : float - last known position size for transition detection
  - equity_at_entry         : float - equity snapshot when last position opened
  - cooldown_bars_remaining : int   - countdown bars until COOLDOWN expires (0 = NORMAL)
"""

from ...core.base.base_component import BaseComponent
from ...core.interfaces.trading_interfaces import ITradingEngine
from ...types import RiskOutput


class risk_manager(BaseComponent):
    """
    Risk manager implementing a three-state machine (NORMAL/COOLDOWN/HALTED).

    Enforces global constraints cascading across all eight trading pathways
    without regime-specific adjustments. The 15% drawdown cap (HALTED) and
    single-position isolation (POSITION LIMIT) are Protected Mechanisms.
    The loss-event-triggered cooldown (COOLDOWN) spaces losing entries by
    3 bars, breaking drawdown accumulation clusters. Universal coverage
    automatically extends to all pathways including new Ranging SHORT
    via regime-agnostic and direction-agnostic design.

    State transitions:
      NORMAL   → COOLDOWN: losing trade exit detected
      NORMAL   → HALTED  : drawdown >= max_drawdown_pct
      COOLDOWN → NORMAL  : cooldown_bars_remaining reaches 0
      COOLDOWN → NORMAL  : new entry resets cooldown (position_opened)
      COOLDOWN → HALTED  : drawdown >= max_drawdown_pct (overrides cooldown)
    """

    def __init__(self, trading_engine: ITradingEngine, **params):
        super().__init__(trading_engine, **params)

        # Extract owned parameters
        self.max_drawdown_pct = self.params['max_drawdown_pct']
        self.cooldown_bars_after_loss = self.params['cooldown_bars_after_loss']
        self.max_concurrent_positions = self.params['max_concurrent_positions']
        self.max_capital_deployed_pct = self.params['max_capital_deployed_pct']

        # Cross-trade state (never reset between trades)
        # equity_high_water_mark: initialized to None; set on first can_trade() call
        self.equity_high_water_mark = None
        # prev_position_size: detects open/close transitions between consecutive bars
        self.prev_position_size = 0
        # equity_at_entry: snapshot of equity when position opened; used for PnL detection
        self.equity_at_entry = None
        # cooldown_bars_remaining: 0 = NORMAL; >0 = COOLDOWN active (countdown)
        self.cooldown_bars_remaining = 0

    def can_trade(self) -> RiskOutput:
        """
        Evaluate risk state machine and determine whether trading is allowed.

        Processing order each bar:
          1. Update equity high water mark and compute drawdown
          2. Detect position state transitions (opened / closed)
          3. Update cooldown state based on transitions and realized PnL
          4. Check HALTED state (drawdown >= max_drawdown_pct)
          5. Check POSITION LIMIT (max 1 concurrent position)
          6. Check COOLDOWN state (bars remaining after losing trade)
          7. Return NORMAL (trading allowed)

        Returns:
            RiskOutput with trading_allowed and diagnostic risk_reason.
        """
        current_equity = self.portfolio.get_total_value()

        # Initialize high water mark on first call
        if self.equity_high_water_mark is None:
            self.equity_high_water_mark = current_equity

        # Update high water mark if equity has grown to a new peak
        if current_equity > self.equity_high_water_mark:
            self.equity_high_water_mark = current_equity

        # Calculate current drawdown from peak (in percent)
        drawdown_pct = (
            (self.equity_high_water_mark - current_equity)
            / self.equity_high_water_mark
            * 100.0
        )

        # --- Detect position state transitions ---
        position = self.portfolio.get_position()
        current_size = (
            abs(position.size)
            if (position is not None and position.size != 0)
            else 0
        )

        position_opened = (self.prev_position_size == 0 and current_size > 0)
        position_closed = (self.prev_position_size > 0 and current_size == 0)

        if position_opened:
            # Record equity at entry; new entry resets any active cooldown per design spec
            self.equity_at_entry = current_equity
            self.cooldown_bars_remaining = 0

        if position_closed and self.equity_at_entry is not None:
            # Measure realized PnL via equity delta since entry
            realized_pnl = current_equity - self.equity_at_entry
            if realized_pnl < 0:
                # Losing trade: activate COOLDOWN for cooldown_bars_after_loss bars
                self.cooldown_bars_remaining = self.cooldown_bars_after_loss
            else:
                # Winning trade: reset cooldown (COOLDOWN → NORMAL)
                self.cooldown_bars_remaining = 0
            self.equity_at_entry = None

        # Update position tracking for next bar's transition detection
        self.prev_position_size = current_size

        # --- Constraint 1: HALTED state (mandatory, non-negotiable) ---
        if drawdown_pct >= self.max_drawdown_pct:
            output = RiskOutput(
                trading_allowed=False,
                risk_reason=(
                    f'HALTED: drawdown {drawdown_pct:.2f}% >= limit {self.max_drawdown_pct:.1f}% '
                    f'(equity={current_equity:.2f}, peak={self.equity_high_water_mark:.2f})'
                ),
                constraint_type='drawdown_limit',
                drawdown_pct=drawdown_pct,
                equity_high_water_mark=self.equity_high_water_mark,
                current_equity=current_equity,
            )
            self.log_risk_output(output)
            return output

        # --- Constraint 2: Position limit (max_concurrent_positions = 1) ---
        if current_size > 0:
            output = RiskOutput(
                trading_allowed=False,
                risk_reason=(
                    f'POSITION LIMIT: {self.max_concurrent_positions} concurrent '
                    f'position(s) already open (size={current_size}). '
                    f'No new entries until current position exits.'
                ),
                constraint_type='position_limit',
                drawdown_pct=drawdown_pct,
                equity_high_water_mark=self.equity_high_water_mark,
                current_equity=current_equity,
                open_position_size=current_size,
            )
            self.log_risk_output(output)
            return output

        # --- Constraint 3: COOLDOWN state (loss-event-triggered entry prohibition) ---
        if self.cooldown_bars_remaining > 0:
            output = RiskOutput(
                trading_allowed=False,
                risk_reason=(
                    f'COOLDOWN: {self.cooldown_bars_remaining} bar(s) remaining after '
                    f'losing trade exit (drawdown={drawdown_pct:.2f}%)'
                ),
                constraint_type='cooldown',
                drawdown_pct=drawdown_pct,
                equity_high_water_mark=self.equity_high_water_mark,
                current_equity=current_equity,
                cooldown_bars_remaining=self.cooldown_bars_remaining,
            )
            self.cooldown_bars_remaining -= 1
            self.log_risk_output(output)
            return output

        # --- NORMAL state: All constraints passed ---
        output = RiskOutput(
            trading_allowed=True,
            risk_reason=(
                f'NORMAL: drawdown {drawdown_pct:.2f}% < limit {self.max_drawdown_pct:.1f}%, '
                f'no open position, no active cooldown '
                f'(equity={current_equity:.2f}, peak={self.equity_high_water_mark:.2f})'
            ),
            drawdown_pct=drawdown_pct,
            equity_high_water_mark=self.equity_high_water_mark,
            current_equity=current_equity,
        )
        self.log_risk_output(output)
        return output
