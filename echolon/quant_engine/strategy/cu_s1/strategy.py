"""
Strategy Main Coordinator - Eight-Pathway Regime-Aware Momentum Strategy

Business Logic Source: workspace/current/strategy/strategy_overview.md

Strategy: Eight-regime entries covering LONG and SHORT directions:
  Preserved pathways:
  - RANGING regime:       MFI oversold (IC=-0.138)              → mean-reversion LONG
  - TRENDING_DOWN regime: OBV < obv_threshold (IC=-0.382)       → trend-continuation SHORT
  - VOLATILE regime:      ADX > adx_threshold (IC=-0.727)       → breakout LONG

  Improved (IC-validated) pathways:
  - TRENDING_UP regime:   MINUS_DM > minus_dm_threshold (IC=-0.226) → counter-trend SHORT
  - VOLATILE regime:      ADXR < adxr_threshold (IC=+0.367)         → exhaustion SHORT

  Modified pathway (SAR decay remediation):
  - TRENDING_UP regime:   close > SAR AND ADX > adx_confirmation   → momentum LONG
                          (ADX confirmation added to filter decayed SAR signals)

  Preserved from prior iteration:
  - TRENDING_DOWN regime: NATR > natr_threshold (>90th pctile)       → counter-trend rebound LONG

  New pathway (PROTECTIVE_EXPAND):
  - RANGING regime:       WILLR > willr_overbought_threshold        → mean-reversion SHORT

Exit:   Regime-specific ATR-based trailing stop ratchet + time backstop
        + additive profit-protection floor (IMPROVED — addresses EXIT_001 profit capture gap):
        Preserved trailing stops:
        - ranging LONG:            4.0× ATR trailing stop, 25-bar backstop
        - trending_up LONG:        3.5× ATR trailing stop, 20-bar backstop
        - trending_down SHORT:     3.5× ATR trailing stop, 20-bar backstop
        - volatile LONG:           4.0× ATR trailing stop, 18-bar backstop
        CASCADE (inherits from preserved):
        - trending_down LONG:      3.5× ATR trailing stop, 20-bar backstop (inherits trending_down)
        - trending_up SHORT:       3.5× ATR trailing stop, 15-bar backstop
        - volatile SHORT:          4.0× ATR trailing stop, 18-bar backstop (inherits volatile LONG)
        - ranging SHORT:           4.0× ATR trailing stop, 25-bar backstop (inherits ranging LONG)
        Profit-protection floor (additive, Priority 2):
        - Activation: unrealized_pnl >= 2.0× initial_risk_amount (2.0R trigger)
        - Floor (LONG):  best_price_seen - 1.0× ATR (evaluated before trailing stop)
        - Floor (SHORT): best_price_seen + 1.0× ATR (evaluated before trailing stop)

Sizing: Fixed percentage risk (8.5% equity per trade) with marginal
        rounding (threshold=0.406) to prevent trade starvation during elevated-volatility
        periods. Uniform across all eight pathways. ATR multiplier 2.437×.

Risk:   Three-state machine: NORMAL → COOLDOWN → HALTED
        - HALTED:   15% drawdown circuit breaker → mandatory flatten + trading halt
        - COOLDOWN: 3-bar entry prohibition after losing trade → exit logic continues
        - NORMAL:   Full entry and exit permission

Market:    SHFE copper futures (cu)
Frequency: Interday (daily bars)
Hook:      ForcedExitStrategyHook — contract expiry forced exits are processed
           AUTOMATICALLY before _execute_bar(). No manual handling required.
"""

from ...core.base.base_strategy import BaseStrategy
from ...core.interfaces.trading_interfaces import ITradingEngine
from ...types import OrderIntent


class strategy_main(BaseStrategy):
    """
    Main coordinator for the Eight-Pathway Regime-Aware Momentum Strategy.

    Orchestrates four components:
      - entry_rule      : Eight-pathway LONG and SHORT signal generation
                          (MFI<threshold in ranging LONG / close>SAR+ADX confirm in trending_up LONG /
                          OBV<threshold in trending_down SHORT / ADX>threshold in volatile LONG /
                          MINUS_DM>threshold in trending_up SHORT / ADXR<threshold in volatile SHORT /
                          NATR>threshold in trending_down LONG / WILLR>threshold in ranging SHORT)
      - exit_rule       : Regime-specific ATR trailing stop ratchet + additive profit-protection
                          floor + time backstop
                          (four preserved + four CASCADE pathways; profit floor activates at 2.0R,
                          evaluated at Priority 2 before trailing stop)
      - risk_manager    : Three-state machine (NORMAL/COOLDOWN/HALTED):
                          drawdown halt + loss-event cooldown + single-position limit
      - position_sizer  : Fixed percentage risk sizing with marginal rounding (all pathways)

    _execute_bar() orchestration sequence (strategy_overview.md):
      1. Risk check
         a. HALTED (drawdown_limit circuit breaker): flatten position → halt all activity
         b. COOLDOWN / POSITION LIMIT: entry prohibited, fall through to exit
         c. NORMAL: proceed to entry evaluation
      2. Entry: generate_signal() → calculate_size() → entry()
         Guard: trading_allowed AND no position AND no pending orders
      3. Exit: should_exit() → exit()
         Guard: has_position AND no pending orders
         Runs even when trading_allowed=False (COOLDOWN/POSITION LIMIT) so trailing stop
         and time backstop can close the existing position normally.

    Contract expiry forced exits are handled AUTOMATICALLY by ForcedExitStrategyHook
    BEFORE _execute_bar() is invoked. DO NOT call check_and_process_forced_exits()
    manually.
    """

    def __init__(self, trading_engine: ITradingEngine, **params):
        super().__init__(trading_engine, **params)
        # Components (entry_rule, exit_rule, risk_manager, position_sizer) are
        # auto-detected and initialised by BaseStrategy.setup_components()
        # during on_start().  No manual wiring required here.

    # ──────────────────────────────────────────────────────────────────────────
    # Lifecycle: Start
    # ──────────────────────────────────────────────────────────────────────────

    def _on_strategy_start(self) -> None:
        """
        Custom startup logic - called AFTER all components and hooks are initialised.

        Override _on_strategy_start() (NOT on_start()) so the base class can
        complete component setup, validation, and hook callbacks first.
        """
        self.log("=" * 70)
        self.log("Eight-Pathway Regime-Aware Momentum Strategy initialising (SHFE Copper / Interday)")
        self.log("-" * 70)
        self.log(
            f"[ENTRY] Pathway 1 (ranging LONG)          : MFI < {self.entry_rule.mfi_oversold_threshold:.1f} "
            f"(mfi_period={self.entry_rule.mfi_period}, IC=-0.138) → LONG"
        )
        self.log(
            f"[ENTRY] Pathway 2 (trending_up LONG)      : close > SAR AND "
            f"ADX > {self.entry_rule.adx_confirmation_threshold:.1f} "
            f"(SAR + ADX confirmation, filters decayed SAR signals) → LONG"
        )
        self.log(
            f"[ENTRY] Pathway 3 (trending_down SHORT)   : OBV z-score < {self.entry_rule.obv_threshold:.2f} "
            f"(IC=-0.382, trend-continuation) → SHORT"
        )
        self.log(
            f"[ENTRY] Pathway 4 (volatile LONG)         : ADX > {self.entry_rule.adx_threshold:.1f} "
            f"(adx_period={self.entry_rule.adx_period}, strength-expansion) → LONG"
        )
        self.log(
            f"[ENTRY] Pathway 5 (trending_up SHORT)     : MINUS_DM > {self.entry_rule.minus_dm_threshold:.1f} "
            f"(IC=-0.226, counter-trend exhaustion) → SHORT"
        )
        self.log(
            f"[ENTRY] Pathway 6 (volatile SHORT)        : ADXR < {self.entry_rule.adxr_threshold:.1f} "
            f"(IC=+0.367, trend exhaustion, low ADXR = no direction) → SHORT"
        )
        self.log(
            f"[ENTRY] Pathway 7 (trending_down LONG)    : NATR > {self.entry_rule.natr_threshold:.2f} "
            f"(natr_period={self.entry_rule.natr_period}, >90th pctile volatility spike rebound) → LONG"
        )
        self.log(
            f"[ENTRY] Pathway 8 (ranging SHORT)         : WILLR > {self.entry_rule.willr_overbought_threshold:.1f} "
            f"(overbought mean-reversion, C9.2 KEEP, PROTECTIVE_EXPAND) → SHORT"
        )
        self.log("-" * 70)
        self.log(
            f"[EXIT]  Trailing stop (ranging LONG)      : {self.exit_rule.atr_multiplier_ranging}× "
            f"ATR({self.exit_rule.atr_period}) below 5d rolling high (ratchet-up)"
        )
        self.log(
            f"[EXIT]  Trailing stop (trending_up LONG)  : {self.exit_rule.atr_multiplier_trending_up}× "
            f"ATR({self.exit_rule.atr_period}) below 5d rolling high (ratchet-up, FIXED)"
        )
        self.log(
            f"[EXIT]  Trailing stop (trending_down SHORT): {self.exit_rule.atr_multiplier_trending_down}× "
            f"ATR({self.exit_rule.atr_period}) above 5d rolling low (ratchet-down)"
        )
        self.log(
            f"[EXIT]  Trailing stop (volatile LONG)     : {self.exit_rule.atr_multiplier_volatile}× "
            f"ATR({self.exit_rule.atr_period}) below 5d rolling high (widest, FIXED)"
        )
        self.log(
            f"[EXIT]  Trailing stop (trending_down LONG): {self.exit_rule.atr_multiplier_trending_down}× "
            f"ATR({self.exit_rule.atr_period}) below 5d rolling high (universal coverage, inherits trending_down)"
        )
        self.log(
            f"[EXIT]  Trailing stop (trending_up SHORT) : {self.exit_rule.atr_multiplier_trending_up_short}× "
            f"ATR({self.exit_rule.atr_period}) above 5d rolling low (CASCADE)"
        )
        self.log(
            f"[EXIT]  Trailing stop (volatile SHORT)    : {self.exit_rule.atr_multiplier_volatile}× "
            f"ATR({self.exit_rule.atr_period}) above 5d rolling low (CASCADE from volatile LONG)"
        )
        self.log(
            f"[EXIT]  Trailing stop (ranging SHORT)     : {self.exit_rule.atr_multiplier_ranging}× "
            f"ATR({self.exit_rule.atr_period}) above 5d rolling low (CASCADE from ranging LONG)"
        )
        self.log(
            f"[EXIT]  Time backstop : "
            f"ranging={self.exit_rule.max_holding_period_ranging} bars | "
            f"trending_up={self.exit_rule.max_holding_period_trending_up} bars | "
            f"trending_down={self.exit_rule.max_holding_period_trending_down} bars | "
            f"volatile={self.exit_rule.max_holding_period_volatile} bars | "
            f"trending_up_short={self.exit_rule.max_holding_period_trending_up_short} bars"
        )
        self.log(
            f"[EXIT]  Profit floor  : activation={self.exit_rule.profit_protection_activation_r_multiple}R "
            f"| floor_width={self.exit_rule.profit_protection_floor_atr_multiple}×ATR "
            f"(Priority 2, evaluated before trailing stop once latched)"
        )
        self.log("-" * 70)
        self.log(
            f"[RISK]  Drawdown halt  : {self.risk_manager.max_drawdown_pct:.1f}% from equity peak "
            f"(HALTED — hard constraint, flatten + halt, all pathways)"
        )
        self.log(
            f"[RISK]  Loss cooldown  : {self.risk_manager.cooldown_bars_after_loss} bars after any losing trade "
            f"(COOLDOWN — entry prohibited, exit continues)"
        )
        self.log(
            f"[RISK]  Position limit : max {self.risk_manager.max_concurrent_positions} "
            f"concurrent position(s)"
        )
        self.log("-" * 70)
        self.log(
            f"[SIZE]  Risk per trade : {self.position_sizer.risk_per_trade_pct:.2f}% equity | "
            f"trailing_atr_mult={self.position_sizer.trailing_atr_multiplier}× | "
            f"contract_multiplier={self.position_sizer.contract_multiplier} | "
            f"marginal_threshold={self.position_sizer.marginal_rounding_threshold}"
        )
        self.log("=" * 70)

    # ──────────────────────────────────────────────────────────────────────────
    # Lifecycle: Bar execution
    # ──────────────────────────────────────────────────────────────────────────

    def _execute_bar(self) -> None:
        """
        Bar-by-bar trading logic for the Eight-Pathway Regime-Aware Momentum Strategy.

        Override _execute_bar() (NOT on_bar()) so the base template method can
        invoke hook callbacks (on_bar_start / on_bar_end) and process forced
        contract-expiry exits BEFORE this method is called.

        Orchestration (strategy_overview.md):
          1. Risk check  →  HALTED (flatten+halt) / COOLDOWN or POSITION LIMIT (entry blocked, exit ok) / NORMAL
          2. Entry logic →  regime filter → indicator signal → size → order
          3. Exit logic  →  trailing stop → time backstop → close order
        """
        # ──────────────────────────────────────────────────────────────────
        # 1. Risk check
        # ──────────────────────────────────────────────────────────────────
        risk_output = self.risk_manager.can_trade()

        if not risk_output.trading_allowed:
            # ── 1a. HALTED (drawdown_limit circuit breaker) ───────────────
            # Per risk_prompt.md: drawdown breach is a hard, non-negotiable
            # halt. Any open position must be closed immediately; no further
            # entries or exits on this bar.
            if risk_output.constraint_type == 'drawdown_limit':
                self.log(f"[RISK] {risk_output.risk_reason}")
                if self.has_position() and not self.has_pending_orders():
                    self.log("[RISK] Flattening position — drawdown halt enforced.")
                    if self.is_long_position():
                        self.exit(OrderIntent.EXIT_LONG)
                    else:
                        self.exit(OrderIntent.EXIT_SHORT)
                return

            # ── 1b. COOLDOWN or POSITION LIMIT ───────────────────────────
            # Entry is prohibited (loss-event cooldown or single-position limit).
            # Exit logic MUST still run so the trailing stop and time backstop
            # can close any open position normally.
            self.log(f"[RISK] {risk_output.risk_reason} — exit evaluation continues.")

        # ──────────────────────────────────────────────────────────────────
        # 2. Entry logic
        # Pre-conditions:
        #   - trading_allowed must be True (drawdown / cooldown / position limit
        #     guards above ensure entry is only attempted in NORMAL state)
        #   - No open position (single-position constraint)
        #   - No pending orders (prevents double-ordering on T+1 execution lag)
        # ──────────────────────────────────────────────────────────────────
        if (
            risk_output.trading_allowed
            and not self.has_position()
            and not self.has_pending_orders()
        ):
            entry_signal = self.entry_rule.generate_signal()

            if entry_signal.signal != 'HOLD':
                sizer_output = self.position_sizer.calculate_size(entry_signal)

                if sizer_output.calculated_size > 0:
                    self.log(
                        f"[ENTRY] Signal={entry_signal.signal} | "
                        f"size={sizer_output.calculated_size} lot(s) | "
                        f"{entry_signal.entry_reason}"
                    )
                    self.entry(entry_signal.intent, sizer_output.calculated_size)
                else:
                    self.log(
                        f"[ENTRY] Signal={entry_signal.signal} suppressed "
                        f"(calculated_size=0): {sizer_output.sizing_reason}"
                    )

        # ──────────────────────────────────────────────────────────────────
        # 3. Exit logic
        # Pre-conditions:
        #   - Open position exists
        #   - No pending orders (prevents duplicate close orders)
        # Note: also executes when trading_allowed=False (COOLDOWN or POSITION
        #       LIMIT) so the trailing stop and time backstop can close the
        #       existing position normally.
        # ──────────────────────────────────────────────────────────────────
        elif self.has_position() and not self.has_pending_orders():
            exit_decision = self.exit_rule.should_exit()

            if exit_decision.should_exit:
                self.log(
                    f"[EXIT] Closing position | "
                    f"bars_held={exit_decision.bars_since_entry} | "
                    f"{exit_decision.exit_reason}"
                )
                self.exit(exit_decision.intent)

    # ──────────────────────────────────────────────────────────────────────────
    # Lifecycle: Stop
    # ──────────────────────────────────────────────────────────────────────────

    def on_stop(self) -> None:
        """Log final state when strategy stops."""
        self.log("=" * 70)
        self.log("Eight-Pathway Regime-Aware Momentum Strategy stopped.")
        if self.risk_manager.equity_high_water_mark is not None:
            self.log(
                f"Final equity high water mark: "
                f"{self.risk_manager.equity_high_water_mark:.2f}"
            )
        self.log("=" * 70)
