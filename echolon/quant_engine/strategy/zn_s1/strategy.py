"""
Strategy Coordinator - Seven-Pathway Regime-Aware SHFE Zinc Futures Strategy
=============================================================================

Zinc Regime-Adaptive Multi-Pathway (Zinc-RAMP) strategy operating across four
market regimes (ranging, trending_up, trending_down, volatile) with seven
entry pathways (three SHORT + three LONG + one SHORT-only = seven total):

  Active Pathways:
    - Ranging SHORT: Negative-IC entry via macd_histogram threshold
      (macd_histogram IC = -0.148, PRESERVED baseline pathway)
    - Ranging LONG: Positive-IC entry via obv threshold
      (obv IC = +0.147, PRESERVED)
    - Trending Up SHORT: Mean-reversion entry via ad (Accumulation/Distribution)
      (PRESERVED: ad IC=-0.235 STRONG, stable)
    - Trending Up LONG: Trend-following entry via minus_di threshold
      (NEW: minus_di IC=+0.20 STRONG, sole positive IC factor in trending_up)
    - Trending Down LONG: Mean-reversion entry via natr threshold
      (PRESERVED: natr IC=+0.425, volatility expansion predicts positive returns)
    - Trending Down SHORT: Momentum-following entry via macd_signal threshold
      (PRESERVED: IC = -0.258)
    - Volatile SHORT: Mean-reversion entry via sma threshold
      (REDESIGNED: sma IC=-0.415 STRONG, replaces degrading adxr pathway)

  Exit Mechanism: HYBRID REGIME-SPECIFIC ARCHITECTURE
    Indicator reversal (4 pathways):
    - ranging SHORT: ATR-based hard stop + macd_histogram reversal + 20-bar backstop
    - trending_up SHORT: ATR-based hard stop + ad reversal + 20-bar backstop
    - trending_down LONG: ATR-based hard stop + natr reversal + 11-bar backstop
    - volatile SHORT: ATR-based hard stop + sma reversal + 20-bar backstop
    Trailing stop (2 pathways):
    - trending_up LONG: ATR-based hard stop + trailing stop (activation + trail) + 17-bar backstop
    - trending_down SHORT: ATR-based hard stop + trailing stop + 14-bar backstop
    Profit target (1 pathway):
    - ranging LONG: ATR-based hard stop + profit target (ATR-based) + 22-bar backstop

  Risk: 15% drawdown circuit breaker (recoverable state machine with
        regime-calibrated recovery windows; trending_up extended 45-bar window)
  Sizing: Fixed percentage risk with ATR-based synthetic stop distance

Orchestration Flow (per strategy_overview.md):
    1. Risk Check      -> risk_manager.can_trade()
    2. Exit Check      -> exit_rule.should_exit() (if position held)
    3. Entry Signal    -> entry_rule.generate_signal() (if no position)
    4. Position Sizing -> position_sizer.calculate_size() (if entry signal)
    5. Order Execution -> self.entry() or self.exit()

Components:
    - entry.py:  Seven-pathway regime-aware entry (macd_histogram, obv, ad,
                 minus_di, natr, macd_signal, sma)
    - exit.py:   Hybrid exit: indicator reversal (4 pathways) +
                 trailing stop (2 pathways) + profit target (1 pathway)
    - risk.py:   Recoverable 15% drawdown circuit breaker with regime-calibrated
                 recovery (trending_up: 45-bar window, trending_down: 60-bar window)
    - sizer.py:  Fixed percentage risk sizing with marginal rounding rescue

Infrastructure (automatic, DO NOT implement):
    - Contract expiry forced exits (ForcedExitStrategyHook)
    - Component setup (BaseStrategy.setup_components)
    - State persistence (save_state / restore_state)

Business Logic Source: workspace/current/strategy/strategy_overview.md
"""

from ...core.base.base_strategy import BaseStrategy
from ...core.interfaces.trading_interfaces import ITradingEngine, OrderIntent


class strategy_main(BaseStrategy):
    """
    Seven-Pathway Regime-Aware SHFE Zinc Futures Strategy (Zinc-RAMP).

    Seven entry pathways across market regimes:
    - Ranging SHORT via macd_histogram negative-IC signal (IC=-0.148, PRESERVED)
    - Ranging LONG via obv positive-IC volume flow signal (IC=+0.147, PRESERVED)
    - Trending Up SHORT via ad above-threshold (IC=-0.235 STRONG, PRESERVED)
    - Trending Up LONG via minus_di threshold (IC=+0.20 STRONG, NEW)
    - Trending Down LONG via natr mean-reversion volatility expansion (IC=+0.425, PRESERVED)
    - Trending Down SHORT via macd_signal momentum-following (IC=-0.258, PRESERVED)
    - Volatile SHORT via sma threshold (IC=-0.415 STRONG, REDESIGNED from adxr)

    Hybrid exit architecture:
    - Indicator reversal (4 pathways): ATR hard stop + reversal + time backstop
    - Trailing stop (2 pathways): trending_up LONG + trending_down SHORT
    - Profit target (1 pathway): ranging LONG
    Standard 20-bar backstop for most SHORT pathways; 11 bars for trending_down LONG;
    14 bars for trending_down SHORT; 17 bars for trending_up LONG; 22 bars for ranging LONG.
    Recoverable 15% drawdown circuit breaker with 4-regime-calibrated recovery windows
    (trending_up: 45 bars, trending_down: 60 bars, volatile: 45 bars, ranging: 32 bars).
    Fixed percentage risk sizing with marginal rounding rescue for zinc futures (5 ton/lot).
    """

    def __init__(self, trading_engine: ITradingEngine, **params):
        super().__init__(trading_engine, **params)
        # Components are automatically initialized by BaseStrategy.setup_components()
        # via on_start() -> entry_rule, exit_rule, risk_manager, position_sizer

    def _on_strategy_start(self) -> None:
        """Custom startup logic after components are initialized."""
        self.log("Seven-Pathway Zinc-RAMP SHFE Zinc Futures Strategy initialized")
        self.log(
            f"Entry pathways (SHORT): "
            f"Ranging SHORT (macd_histogram > {self.entry_rule.entry_macd_histogram_threshold:.2f}), "
            f"Trending Down SHORT (macd_signal > {self.entry_rule.entry_macd_signal_threshold:.2f}), "
            f"Volatile SHORT (sma > {self.entry_rule.entry_sma_threshold:.0f}), "
            f"Trending Up SHORT (ad > {self.entry_rule.entry_ad_threshold:.0f})"
        )
        self.log(
            f"Entry pathways (LONG): "
            f"Ranging LONG (obv > {self.entry_rule.entry_obv_threshold:.0f}), "
            f"Trending Down LONG (natr > {self.entry_rule.entry_natr_threshold:.4f}), "
            f"Trending Up LONG (minus_di > {self.entry_rule.entry_minus_di_threshold:.2f})"
        )
        self.log(
            f"Exit: Hybrid architecture, "
            f"backstops (bars): default=20, trending_down_long=11, "
            f"trending_down_short=14, trending_up_long=17, ranging_long=22"
        )
        self.log(
            f"Exit mechanisms: "
            f"trailing (trending_up LONG/trending_down SHORT): "
            f"activation={self.exit_rule.exit_trailing_activation_atr_mult:.2f}x ATR, "
            f"trail={self.exit_rule.exit_trailing_atr_multiplier:.2f}x ATR; "
            f"ranging LONG: profit_target={self.exit_rule.exit_profit_target_atr_mult_ranging_long:.1f}x ATR; "
            f"ATR period={self.exit_rule.exit_atr_period}"
        )
        self.log(
            f"Risk: Max drawdown {self.risk_manager.max_drawdown_pct:.1f}% "
            f"(ranging: {self.risk_manager.recovery_observation_window_bars} bars, "
            f"buffer {self.risk_manager.recovery_drawdown_buffer_pct:.2f}%; "
            f"trending_up: {self.risk_manager.recovery_observation_window_bars_trending_up} bars, "
            f"buffer {self.risk_manager.recovery_drawdown_buffer_pct_trending_up:.1f}%; "
            f"trending_down: {self.risk_manager.recovery_observation_window_bars_trending_down} bars, "
            f"buffer {self.risk_manager.recovery_drawdown_buffer_pct_trending_down:.1f}%; "
            f"volatile: {self.risk_manager.recovery_observation_window_bars_volatile} bars, "
            f"buffer {self.risk_manager.recovery_drawdown_buffer_pct_volatile:.1f}%), "
            f"Max positions {self.risk_manager.max_concurrent_positions}"
        )
        self.log(
            f"Sizing: {self.position_sizer.risk_per_trade_pct:.2f}% risk/trade, "
            f"ATR({self.position_sizer.atr_period}) multiplier={self.position_sizer.sizing_atr_multiplier}, "
            f"contract multiplier={self.position_sizer.contract_multiplier}, "
            f"max lots={self.position_sizer.max_position_lots}, "
            f"marginal threshold={self.position_sizer.marginal_rounding_threshold:.2f}"
        )

    def _execute_bar(self) -> None:
        """
        Main trading logic executed on each bar.

        Override _execute_bar() (NOT on_bar()) per BaseStrategy template method pattern.
        Contract expiry forced exits are handled automatically BEFORE this method.

        Orchestration:
            1. Risk check (circuit breaker + drawdown monitoring)
            2. If halted -> flatten position and return (capital protection)
            3. If has position -> evaluate exit conditions
            4. If no position -> generate entry signal, size, and submit order
        """
        # =====================================================================
        # Step 1: Risk Assessment
        # =====================================================================
        risk_output = self.risk_manager.can_trade()

        # Circuit breaker halt: Flatten open positions then suspend
        # Per risk_prompt.md: "immediate flattening protocol" on drawdown breach.
        # Risk halt overrides entry, exit backstop, and ongoing trade continuation.
        # Capital protection: close any open position before halting to prevent
        # drawdown worsening from trapped positions during suspension.
        if not risk_output.trading_allowed:
            if self.has_position() and not self.has_pending_orders():
                if self.is_short_position():
                    self.exit(OrderIntent.EXIT_SHORT)
                elif self.is_long_position():
                    self.exit(OrderIntent.EXIT_LONG)
            return

        # =====================================================================
        # Step 2: Exit Evaluation (if position held)
        # =====================================================================
        # Check exits BEFORE entries to ensure clean position management.
        # Must also check has_pending_orders() to prevent duplicate orders.
        if self.has_position() and not self.has_pending_orders():
            exit_output = self.exit_rule.should_exit()

            if exit_output.should_exit:
                self.exit(exit_output.intent)
                return

        # =====================================================================
        # Step 3: Entry Signal Generation (if no position)
        # =====================================================================
        # Only evaluate entries when:
        # - trading_allowed is True (risk check passed above)
        # - No current position
        # - No pending orders (prevent duplicate order submission)
        if not self.has_position() and not self.has_pending_orders():
            entry_output = self.entry_rule.generate_signal()

            if entry_output.signal != 'HOLD':
                # Step 4: Position Sizing
                sizer_output = self.position_sizer.calculate_size(entry_output)

                if sizer_output.calculated_size > 0:
                    # Step 5: Order Submission
                    self.entry(entry_output.intent, sizer_output.calculated_size)

    def on_stop(self) -> None:
        """Called when strategy stops - log final state."""
        self.log("Strategy stopped - Seven-Pathway Zinc-RAMP SHFE Zinc Futures Strategy")
