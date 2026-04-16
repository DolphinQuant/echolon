"""
Exit Component - Regime-Adaptive ATR Exit Framework
====================================================

Eight regime-specific exit pathways. Six pathways use fixed parameters
from strategy_params.py. Pathways for trending_down LONG and trending_down
SHORT use optimizable FLOAT parameters.

Exit priority: Stop loss -> Profit target -> Time-based

Parameters from strategy_params.py:
- exit_atr_period: [10, 30] default 17 (INT, optimizable)
- exit_trending_up_long_stop_mult: 1.571 (FIXED)
- exit_trending_up_long_target_mult: 3.207 (FIXED)
- exit_trending_down_short_stop_mult: [1.0, 2.5] default 1.571 (FLOAT, optimizable)
- exit_trending_down_short_target_mult: [1.0, 2.5] default 3.207 (FLOAT, optimizable)
- exit_ranging_long_stop_mult: 0.919 (FIXED)
- exit_ranging_long_target_mult: 1.098 (FIXED)
- exit_ranging_long_max_bars: 4.8 (FIXED)
- exit_ranging_short_stop_mult: 0.9 (FIXED)
- exit_ranging_short_target_mult: 1.1 (FIXED)
- exit_ranging_short_max_bars: 5.0 (FIXED)
- exit_trending_up_short_stop_mult: 1.2 (FIXED)
- exit_trending_up_short_target_mult: 1.5 (FIXED)
- exit_trending_up_short_max_bars: 3.0 (FIXED)
- exit_volatile_long_stop_mult: 2.5 (FIXED)
- exit_volatile_long_target_mult: 1.8 (FIXED)
- exit_volatile_long_max_bars: 4.0 (FIXED)
- exit_volatile_short_stop_mult: 2.948 (FIXED)
- exit_volatile_short_target_mult: 1.77 (FIXED)
- exit_volatile_short_max_bars: 3.83 (FIXED)
- exit_trending_down_long_stop_mult: [1.0, 2.5] default 1.252 (FLOAT, optimizable)
- exit_trending_down_long_target_mult: [1.0, 2.5] default 1.408 (FLOAT, optimizable)
- exit_trending_down_long_max_bars: [2.0, 6.0] default 2.577 (FLOAT, optimizable)

Indicators: ATR (Tier 1: 'atr_{period}'), market_regime (Tier 3)
"""

from typing import Dict, Any

from ...core.base.base_component import BaseComponent
from ...core.interfaces.trading_interfaces import ITradingEngine, OrderIntent
from ...types import ExitSignalOutput


class exit_rule(BaseComponent):
    """
    Regime-adaptive ATR-based exit manager with eight distinct pathways.

    All pathway parameters are read from strategy_params.py via self.params.
    Six pathways use FIXED parameters. Trending_down LONG and trending_down
    SHORT use optimizable FLOAT parameters (CASCADE_RECALIBRATED).
    """

    def __init__(self, trading_engine: ITradingEngine, **params):
        super().__init__(trading_engine, **params)

        # ATR period (optimizable INT, shared with sizer)
        self.atr_period = self.params['exit_atr_period']

        # Trending_up LONG pathway (FIXED)
        self.trending_up_long_stop_mult = self.params['exit_trending_up_long_stop_mult']
        self.trending_up_long_target_mult = self.params['exit_trending_up_long_target_mult']

        # Trending_down SHORT pathway (optimizable FLOAT, CASCADE_RECALIBRATED)
        self.trending_down_short_stop_mult = self.params['exit_trending_down_short_stop_mult']
        self.trending_down_short_target_mult = self.params['exit_trending_down_short_target_mult']

        # Ranging LONG pathway (FIXED)
        self.ranging_long_stop_mult = self.params['exit_ranging_long_stop_mult']
        self.ranging_long_target_mult = self.params['exit_ranging_long_target_mult']
        self.ranging_long_max_bars = self.params['exit_ranging_long_max_bars']

        # Ranging SHORT pathway (FIXED)
        self.ranging_short_stop_mult = self.params['exit_ranging_short_stop_mult']
        self.ranging_short_target_mult = self.params['exit_ranging_short_target_mult']
        self.ranging_short_max_bars = self.params['exit_ranging_short_max_bars']

        # Trending_up SHORT pathway (FIXED)
        self.trending_up_short_stop_mult = self.params['exit_trending_up_short_stop_mult']
        self.trending_up_short_target_mult = self.params['exit_trending_up_short_target_mult']
        self.trending_up_short_max_bars = self.params['exit_trending_up_short_max_bars']

        # Volatile LONG pathway (FIXED)
        self.volatile_long_stop_mult = self.params['exit_volatile_long_stop_mult']
        self.volatile_long_target_mult = self.params['exit_volatile_long_target_mult']
        self.volatile_long_max_bars = self.params['exit_volatile_long_max_bars']

        # Volatile SHORT pathway (FIXED)
        self.volatile_short_stop_mult = self.params['exit_volatile_short_stop_mult']
        self.volatile_short_target_mult = self.params['exit_volatile_short_target_mult']
        self.volatile_short_max_bars = self.params['exit_volatile_short_max_bars']

        # Trending_down LONG pathway (optimizable FLOAT)
        self.trending_down_long_stop_mult = self.params['exit_trending_down_long_stop_mult']
        self.trending_down_long_target_mult = self.params['exit_trending_down_long_target_mult']
        self.trending_down_long_max_bars = self.params['exit_trending_down_long_max_bars']

        # State variables for position tracking
        self.stop_price = None
        self.take_profit_price = None
        self.entry_price_tracked = None
        self.bars_in_position = 0
        self.entry_regime = None

    def should_exit(self) -> ExitSignalOutput:
        """
        Evaluate exit conditions based on the regime at entry.

        Eight pathway selection (determined at entry, persisted via entry_regime):
        - trending_up LONG: 1.571 stop, 3.207 target, no time exit (FIXED)
        - trending_down SHORT: optimizable stop/target, no time exit (CASCADE)
        - ranging LONG: 0.919 stop, 1.098 target, 4.8 bars (FIXED)
        - ranging SHORT: 0.9 stop, 1.1 target, 5 bars (FIXED)
        - trending_up SHORT: 1.2 stop, 1.5 target, 3 bars (FIXED)
        - volatile LONG: 2.5 stop, 1.8 target, 4.0 bars (FIXED)
        - volatile SHORT: 2.948 stop, 1.77 target, 3.83 bars (FIXED)
        - trending_down LONG: optimizable stop/target/max_bars

        Priority: stop_loss -> profit_target -> time_based

        Returns:
            ExitSignalOutput with exit decision and diagnostics
        """
        position = self.portfolio.get_position()

        # No position - nothing to exit
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

        # Track bars in position
        self.bars_in_position += 1

        # Get current market data
        current_price = self.get_current_price()
        atr = self.get_indicator(f'atr_{self.atr_period}')
        entry_price = position.avg_price
        is_long = position.direction == 'LONG'

        # Initialize stop and target levels on first bar of position
        if self.stop_price is None:
            self.entry_price_tracked = entry_price
            self._initialize_levels(entry_price, atr, is_long)

        # Evaluate exit conditions
        should_exit = False
        intent = None
        exit_reason = ''
        max_bars = None

        # Determine exit intent based on position direction
        exit_intent = OrderIntent.EXIT_LONG if is_long else OrderIntent.EXIT_SHORT

        # Check stop loss (highest priority - protect capital first)
        if self._is_stop_loss_hit(current_price, is_long):
            should_exit = True
            intent = exit_intent
            direction_str = 'LONG' if is_long else 'SHORT'
            stop_mult, target_mult = self._get_pathway_multipliers()
            exit_reason = (
                f'Stop loss hit ({self.entry_regime} {direction_str}): '
                f'price {current_price:.2f} vs '
                f'stop {self.stop_price:.2f} '
                f'(entry {self.entry_price_tracked:.2f}, '
                f'{stop_mult:.3f}x ATR {atr:.2f})'
            )

        # Check profit target
        elif self._is_profit_target_hit(current_price, is_long):
            should_exit = True
            intent = exit_intent
            direction_str = 'LONG' if is_long else 'SHORT'
            stop_mult, target_mult = self._get_pathway_multipliers()
            exit_reason = (
                f'Profit target hit ({self.entry_regime} {direction_str}): '
                f'price {current_price:.2f} vs '
                f'target {self.take_profit_price:.2f} '
                f'(entry {self.entry_price_tracked:.2f}, '
                f'{target_mult:.3f}x ATR {atr:.2f})'
            )

        # Check time-based exit (lowest priority - pathways with max_bars defined)
        else:
            max_bars = self._get_max_holding_bars()
            if max_bars is not None and self.bars_in_position >= max_bars:
                should_exit = True
                intent = exit_intent
                direction_str = 'LONG' if is_long else 'SHORT'
                exit_reason = (
                    f'Time exit ({self.entry_regime} {direction_str}): '
                    f'bars {self.bars_in_position} >= max {max_bars}'
                )

        # Holding reason when no exit triggered
        if not should_exit:
            direction_str = 'LONG' if is_long else 'SHORT'
            holding_detail = f'price {current_price:.2f}, stop {self.stop_price:.2f}, target {self.take_profit_price:.2f}'
            if max_bars is not None:
                holding_detail += f', bars {self.bars_in_position}/{max_bars}'
            exit_reason = (
                f'Holding {self.entry_regime} {direction_str} (day {self.bars_in_position}): '
                f'{holding_detail}, ATR {atr:.2f}'
            )

        # Capture values before potential reset
        bars_since_entry = self.bars_in_position
        final_stop_price = self.stop_price
        final_take_profit_price = self.take_profit_price
        final_entry_regime = self.entry_regime

        # Reset state on exit
        if should_exit:
            self._reset_state()

        output = ExitSignalOutput(
            should_exit=should_exit,
            exit_reason=exit_reason,
            position_size=abs(position.size),
            bars_since_entry=bars_since_entry,
            intent=intent,
            atr_value=atr,
            stop_price=final_stop_price,
            take_profit_price=final_take_profit_price,
            current_price=current_price,
            entry_price=entry_price,
            entry_regime=final_entry_regime
        )

        self.log_exit_output(output)
        return output

    def _initialize_levels(self, entry_price: float, atr: float, is_long: bool) -> None:
        """
        Initialize stop and target levels based on entry regime and direction.

        Eight pathway mappings:
        - trending_up + LONG -> trending_up_long pathway (1.571/3.207, no time exit)
        - trending_down + SHORT -> trending_down_short pathway (optimizable, no time exit)
        - ranging + LONG -> ranging_long pathway (0.919/1.098, 4.8 bars)
        - ranging + SHORT -> ranging_short pathway (0.9/1.1, 5 bars)
        - trending_up + SHORT -> trending_up_short pathway (1.2/1.5, 3 bars)
        - volatile + LONG -> volatile_long pathway (2.5/1.8, 4.0 bars)
        - volatile + SHORT -> volatile_short pathway (2.948/1.77, 3.83 bars)
        - trending_down + LONG -> trending_down_long pathway (optimizable)
        """
        regime = self.get_market_regime()

        # Trending_up LONG pathway
        if regime == 'trending_up' and is_long:
            self.entry_regime = 'trending_up'
            stop_mult = self.trending_up_long_stop_mult
            target_mult = self.trending_up_long_target_mult

        # Trending_down SHORT pathway
        elif regime == 'trending_down' and not is_long:
            self.entry_regime = 'trending_down'
            stop_mult = self.trending_down_short_stop_mult
            target_mult = self.trending_down_short_target_mult

        # Ranging LONG pathway
        elif regime == 'ranging' and is_long:
            self.entry_regime = 'ranging_long'
            stop_mult = self.ranging_long_stop_mult
            target_mult = self.ranging_long_target_mult

        # Ranging SHORT pathway
        elif regime == 'ranging' and not is_long:
            self.entry_regime = 'ranging_short'
            stop_mult = self.ranging_short_stop_mult
            target_mult = self.ranging_short_target_mult

        # Trending_up SHORT pathway (contrarian)
        elif regime == 'trending_up' and not is_long:
            self.entry_regime = 'trending_up_short'
            stop_mult = self.trending_up_short_stop_mult
            target_mult = self.trending_up_short_target_mult

        # Volatile SHORT pathway
        elif regime == 'volatile' and not is_long:
            self.entry_regime = 'volatile_short'
            stop_mult = self.volatile_short_stop_mult
            target_mult = self.volatile_short_target_mult

        # Volatile LONG pathway (mean-reversion bounce)
        elif regime == 'volatile' and is_long:
            self.entry_regime = 'volatile_long'
            stop_mult = self.volatile_long_stop_mult
            target_mult = self.volatile_long_target_mult

        # Trending_down LONG pathway (contrarian bounce - optimizable)
        elif regime == 'trending_down' and is_long:
            self.entry_regime = 'trending_down_long'
            stop_mult = self.trending_down_long_stop_mult
            target_mult = self.trending_down_long_target_mult

        # Defensive: any uncovered regime+direction uses trending_up LONG multipliers
        else:
            self.entry_regime = regime
            stop_mult = self.trending_up_long_stop_mult
            target_mult = self.trending_up_long_target_mult

        if is_long:
            self.stop_price = entry_price - (stop_mult * atr)
            self.take_profit_price = entry_price + (target_mult * atr)
        else:
            self.stop_price = entry_price + (stop_mult * atr)
            self.take_profit_price = entry_price - (target_mult * atr)

    def _get_pathway_multipliers(self) -> tuple:
        """Return (stop_mult, target_mult) for the current entry_regime."""
        if self.entry_regime == 'trending_up':
            return self.trending_up_long_stop_mult, self.trending_up_long_target_mult
        elif self.entry_regime == 'trending_down':
            return self.trending_down_short_stop_mult, self.trending_down_short_target_mult
        elif self.entry_regime == 'ranging_long':
            return self.ranging_long_stop_mult, self.ranging_long_target_mult
        elif self.entry_regime == 'ranging_short':
            return self.ranging_short_stop_mult, self.ranging_short_target_mult
        elif self.entry_regime == 'trending_up_short':
            return self.trending_up_short_stop_mult, self.trending_up_short_target_mult
        elif self.entry_regime == 'volatile_short':
            return self.volatile_short_stop_mult, self.volatile_short_target_mult
        elif self.entry_regime == 'volatile_long':
            return self.volatile_long_stop_mult, self.volatile_long_target_mult
        elif self.entry_regime == 'trending_down_long':
            return self.trending_down_long_stop_mult, self.trending_down_long_target_mult
        return self.trending_up_long_stop_mult, self.trending_up_long_target_mult

    def _get_max_holding_bars(self):
        """Return max holding bars for time-based exit, or None if no time limit."""
        if self.entry_regime == 'ranging_long':
            return self.ranging_long_max_bars
        elif self.entry_regime == 'ranging_short':
            return self.ranging_short_max_bars
        elif self.entry_regime == 'trending_up_short':
            return self.trending_up_short_max_bars
        elif self.entry_regime == 'volatile_short':
            return self.volatile_short_max_bars
        elif self.entry_regime == 'volatile_long':
            return self.volatile_long_max_bars
        elif self.entry_regime == 'trending_down_long':
            return self.trending_down_long_max_bars
        return None

    def _is_profit_target_hit(self, current_price: float, is_long: bool) -> bool:
        """Check if profit target is hit."""
        if is_long:
            return current_price >= self.take_profit_price
        return current_price <= self.take_profit_price

    def _is_stop_loss_hit(self, current_price: float, is_long: bool) -> bool:
        """Check if stop loss is hit."""
        if is_long:
            return current_price <= self.stop_price
        return current_price >= self.stop_price

    def _reset_state(self) -> None:
        """Reset all position-tracking state variables."""
        self.stop_price = None
        self.take_profit_price = None
        self.entry_price_tracked = None
        self.bars_in_position = 0
        self.entry_regime = None

    def _get_component_specific_state(self) -> Dict[str, Any]:
        """Return exit-specific state for live trading persistence."""
        return {
            'stop_price': self.stop_price,
            'take_profit_price': self.take_profit_price,
            'entry_price_tracked': self.entry_price_tracked,
            'bars_in_position': self.bars_in_position,
            'entry_regime': self.entry_regime
        }

    def _restore_component_specific_state(self, state: Dict[str, Any]) -> None:
        """Restore exit-specific state from persistence."""
        self.stop_price = state['stop_price']
        self.take_profit_price = state['take_profit_price']
        self.entry_price_tracked = state['entry_price_tracked']
        self.bars_in_position = state['bars_in_position']
        self.entry_regime = state['entry_regime']
