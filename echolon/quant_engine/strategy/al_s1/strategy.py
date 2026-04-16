"""
Strategy Coordinator - Regime-Aware SHFE Aluminum Futures Strategy
===================================================================

SHFE Aluminum futures strategy with eight entry pathways across four regimes,
implementing bidirectional coverage with PPO-based trending_down SHORT entry,
volatile LONG alpha capture, and trending_down LONG contrarian
mean-reversion via ATR+MFI composite:

  Preserved Pathways:
    - Trending Up LONG:    Aroon Oscillator momentum continuation
    - Trending Up SHORT:   TRIX contrarian
    - Ranging LONG:        MACD histogram mean-reversion (PF 3.4)
    - Ranging SHORT:       TEMA contrarian
    - Trending Down LONG:  ATR+MFI composite contrarian (IC 0.115/0.136)
    - Volatile LONG:       MACD histogram extreme negative tail (PF 11.17)
    - Volatile SHORT:      AD distribution

  Redesigned Pathway:
    - Trending Down SHORT: PPO-based entry (IC -0.175, negative tail IC -0.435)

Orchestration Flow (per strategy_overview.md):
    1. Risk Check     -> risk_manager.can_trade()
    2. Exit Check     -> exit_rule.should_exit() (if position held)
    3. Entry Signal   -> entry_rule.generate_signal() (if no position)
    4. Position Sizing -> position_sizer.calculate_size() (if entry signal)
    5. Order Execution -> self.entry() or self.exit()

Components:
    - entry.py:  Eight-pathway entry (AroonOsc, MACD histogram, TEMA, TRIX, AD, ATR, MFI, PPO)
    - exit.py:   Regime-adaptive ATR exit (8 pathway configurations)
    - risk.py:   15% drawdown circuit breaker + position limits
    - sizer.py:  Inverse volatility risk-based sizing with regime-aware stop selection

Infrastructure (automatic, DO NOT implement):
    - Contract expiry forced exits (ForcedExitStrategyHook)
    - Component setup (BaseStrategy.setup_components)
    - State persistence (save_state / restore_state)
"""

from ...core.base.base_strategy import BaseStrategy
from ...core.interfaces.trading_interfaces import ITradingEngine, OrderIntent


class strategy_main(BaseStrategy):
    """
    Regime-Aware SHFE Aluminum Futures Strategy.

    Eight-pathway strategy with PPO-based trending_down SHORT entry,
    volatile LONG alpha capture via MACD histogram extreme negative tail,
    and trending_down LONG contrarian mean-reversion via ATR+MFI composite.
    Preserves protected ranging MACD mean-reversion (PF 3.4) and volatile
    LONG (PF 11.17). Uses regime-specific ATR exits with eight pathway
    configurations. Inverse volatility risk-based sizing with
    regime-conditional stop multipliers.
    """

    def __init__(self, trading_engine: ITradingEngine, **params):
        super().__init__(trading_engine, **params)
        # Components are automatically initialized by BaseStrategy.setup_components()
        # via on_start() -> entry_rule, exit_rule, risk_manager, position_sizer

    def _on_strategy_start(self) -> None:
        """Custom startup logic after components are initialized."""
        self.log("Regime-Aware SHFE Aluminum Strategy initialized")
        self.log(
            f"Entry Preserved: AroonOsc(period={self.entry_rule.aroonosc_period}, "
            f"threshold={self.entry_rule.aroonosc_long_threshold}) for trending_up LONG, "
            f"MACD histogram (threshold={self.entry_rule.macd_histogram_ranging_long_threshold}) "
            f"for ranging LONG, "
            f"TEMA(period={self.entry_rule.tema_period}, "
            f"threshold={self.entry_rule.entry_tema_ranging_short_threshold}) for ranging SHORT, "
            f"TRIX(period={self.entry_rule.trix_period}, "
            f"threshold={self.entry_rule.entry_trix_trending_up_short_threshold}) "
            f"for trending_up SHORT, "
            f"MACD histogram "
            f"(threshold={self.entry_rule.entry_macd_histogram_volatile_long_threshold}) "
            f"for volatile LONG, "
            f"AD (threshold={self.entry_rule.entry_ad_short_threshold}) "
            f"for volatile SHORT, "
            f"ATR(period={self.entry_rule.atr_period}, "
            f"threshold={self.entry_rule.entry_atr_trending_down_long_threshold}) + "
            f"MFI(period={self.entry_rule.mfi_period}, "
            f"threshold={self.entry_rule.entry_mfi_trending_down_long_threshold}) "
            f"composite for trending_down LONG"
        )
        self.log(
            f"Entry Redesigned: PPO(threshold="
            f"{self.entry_rule.entry_ppo_trending_down_short_threshold}) "
            f"for trending_down SHORT"
        )
        self.log(
            f"Exit: Trending Up LONG={self.exit_rule.trending_up_long_stop_mult}x/"
            f"{self.exit_rule.trending_up_long_target_mult}x ATR, "
            f"Ranging LONG={self.exit_rule.ranging_long_stop_mult}x/"
            f"{self.exit_rule.ranging_long_target_mult}x ATR, "
            f"Volatile LONG={self.exit_rule.volatile_long_stop_mult}x stop ATR, "
            f"Trending Down LONG={self.exit_rule.trending_down_long_stop_mult}x/"
            f"{self.exit_rule.trending_down_long_target_mult}x ATR "
            f"(max {self.exit_rule.trending_down_long_max_bars} bars), "
            f"ATR period={self.exit_rule.atr_period}"
        )
        self.log(
            f"Risk: Max drawdown {self.risk_manager.max_drawdown_pct}%, "
            f"Max positions {self.risk_manager.max_concurrent_positions}"
        )
        self.log(
            f"Sizing: {self.position_sizer.risk_per_trade_pct}% risk/trade, "
            f"multiplier={self.position_sizer.contract_multiplier}, "
            f"max lots={self.position_sizer.max_position_size}, "
            f"marginal threshold={self.position_sizer.marginal_rounding_threshold}"
        )

    def _execute_bar(self) -> None:
        """
        Main trading logic executed on each bar.

        Override _execute_bar() (NOT on_bar()) per BaseStrategy template method pattern.
        Contract expiry forced exits are handled automatically BEFORE this method.

        Orchestration:
            1. Risk check (circuit breaker + drawdown monitoring)
            2. If halted -> flatten position and return (strategy suspension per risk_prompt.md)
            3. If has position -> evaluate exit conditions
            4. If no position -> generate entry signal, size, and submit order
        """
        # =====================================================================
        # Step 1: Risk Assessment
        # =====================================================================
        risk_output = self.risk_manager.can_trade()

        # Circuit breaker halt: Flatten open positions then suspend
        # Per risk_prompt.md: "flatten position immediately, suspend trading"
        # Capital protection: close any open position before halting to prevent
        # drawdown worsening from trapped positions during suspension.
        if not risk_output.trading_allowed:
            if self.has_position() and not self.has_pending_orders():
                if self.is_long_position():
                    self.exit(OrderIntent.EXIT_LONG)
                elif self.is_short_position():
                    self.exit(OrderIntent.EXIT_SHORT)
            return

        # =====================================================================
        # Step 2: Exit Evaluation (if position held)
        # =====================================================================
        # Check exits BEFORE entries to ensure clean position management
        # Must also check has_pending_orders() to prevent duplicate orders
        if self.has_position() and not self.has_pending_orders():
            exit_output = self.exit_rule.should_exit()

            if exit_output.should_exit:
                self.exit(exit_output.intent)
                return

        # =====================================================================
        # Step 3: Entry Signal Generation (if no position)
        # =====================================================================
        # Only evaluate entries when:
        # - trading_allowed is True (risk check passed)
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
        self.log("Strategy stopped - Regime-Aware SHFE Aluminum Strategy")
