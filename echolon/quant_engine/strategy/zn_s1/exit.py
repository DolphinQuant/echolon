"""
Exit Component - Six-Pathway Hybrid Exit Framework
Reversal (4): ranging SHORT / trending_up SHORT (ad) / trending_down LONG / volatile SHORT (sma)
Trailing (2): trending_up LONG / trending_down SHORT | Profit target (1): ranging LONG
"""

from typing import Dict, Any

from ...core.base.base_component import BaseComponent
from ...core.interfaces.trading_interfaces import ITradingEngine, OrderIntent
from ...types import ExitSignalOutput

# Fixed stop ATR multipliers for pathways with non-optimizable stops (calibrated, not optimized)
_STOP_ATR_RANGING = 0.8           # ranging_short
_STOP_ATR_RANGING_LONG = 0.8      # ranging_long
_STOP_ATR_TRENDING_UP = 0.9       # trending_up_short
_STOP_ATR_TRENDING_DOWN = 0.95    # trending_down_short + trending_down_long

# Pathways that hold LONG positions
_LONG_PATHWAYS = ('trending_down_long', 'trending_up_long', 'ranging_long')


class exit_rule(BaseComponent):
    """Six-pathway regime-specific exit manager: 4 reversal, 2 trailing, 1 profit-target."""

    def __init__(self, trading_engine: ITradingEngine, **params):
        super().__init__(trading_engine, **params)

        self.exit_atr_period = self.params['exit_atr_period']
        # Optimizable hard stop multipliers (pathway-specific, formerly fixed constants)
        self.exit_hard_stop_atr_mult_volatile_short = self.params['exit_hard_stop_atr_mult_volatile_short']
        self.exit_hard_stop_atr_mult_trending_up_long = self.params['exit_hard_stop_atr_mult_trending_up_long']
        # Indicator thresholds shared with entry
        self.entry_macd_histogram_threshold = self.params['entry_macd_histogram_threshold']
        self.entry_ad_threshold = self.params['entry_ad_threshold']
        self.entry_natr_threshold = self.params['entry_natr_threshold']
        self.entry_sma_threshold = self.params['entry_sma_threshold']
        # Indicator periods shared with entry
        self.entry_sma_period = self.params['entry_sma_period']
        # Trailing stop and profit target params
        self.exit_trailing_activation_atr_mult = self.params['exit_trailing_activation_atr_mult']
        self.exit_trailing_atr_multiplier = self.params['exit_trailing_atr_multiplier']
        self.exit_profit_target_atr_mult_ranging_long = self.params['exit_profit_target_atr_mult_ranging_long']
        # Time backstop params (loaded from params, fixed values defined in strategy_params.py)
        self.exit_time_backstop_trending_up_long = self.params['exit_time_backstop_trending_up_long']
        self.exit_time_backstop_volatile_short = self.params['exit_time_backstop_volatile_short']
        self.exit_time_backstop_trending_down_long = self.params['exit_time_backstop_trending_down_long']
        self.exit_time_backstop_trending_down_short = self.params['exit_time_backstop_trending_down_short']
        self.exit_time_backstop_ranging_long = self.params['exit_time_backstop_ranging_long']
        self.exit_time_backstop_default = self.params['exit_time_backstop_default']

        # Per-trade state variables
        self.bars_in_position = 0
        self.entry_pathway = None
        self.entry_price = None
        self.stop_price = None
        self.highest_price_since_entry = None
        self.lowest_price_since_entry = None
        self.trailing_stop_price = None
        self.trailing_activated = False
        self.profit_target_price = None

    def should_exit(self) -> ExitSignalOutput:
        """Evaluate exit conditions for six pathways (3 SHORT + 3 LONG)."""
        position = self.portfolio.get_position()

        # No position - reset state and return
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

        current_price = self.get_current_price()

        # First bar of position: detect pathway and initialize exit levels
        if self.entry_pathway is None:
            self.bars_in_position = 0
            self._detect_entry_pathway(position)
            self.entry_price = position.entry_price
            self._compute_stop_price()
            self._initialize_exit_levels()

        is_long_pathway = self.entry_pathway in _LONG_PATHWAYS
        exit_intent = OrderIntent.EXIT_LONG if is_long_pathway else OrderIntent.EXIT_SHORT
        self.bars_in_position += 1

        # Update trailing stop for trailing-stop pathways before exit checks
        if self.entry_pathway in ('trending_up_long', 'trending_down_short'):
            self._update_trailing_stop(current_price)

        macd_hist = self.get_indicator('macd_histogram')
        ad = self.get_indicator('ad')
        # NATR at fixed period 14 — matches entry.py natr_14 for consistent reversal check
        natr = self.get_indicator('natr_14')
        sma = self.get_indicator(f'sma_{self.entry_sma_period}')

        should_exit = False
        intent = None
        exit_reason = ''

        # ---- Highest priority: Hard stop-loss (pathway-specific) ----
        if self.stop_price is not None:
            stop_hit = (current_price < self.stop_price) if is_long_pathway else (current_price > self.stop_price)
            if stop_hit:
                should_exit = True
                intent = exit_intent
                cmp = '<' if is_long_pathway else '>'
                exit_reason = (
                    f'Hard stop-loss ({self.entry_pathway}): '
                    f'price {current_price:.2f} {cmp} stop {self.stop_price:.2f} '
                    f'(entry {self.entry_price:.2f}, day {self.bars_in_position})'
                )

        # ---- Secondary: Pathway-specific exit mechanism ----
        if not should_exit:
            if self.entry_pathway == 'trending_up_long':
                # Trailing stop (LONG): price drops below trailing stop
                if self.trailing_activated and current_price <= self.trailing_stop_price:
                    should_exit = True
                    intent = exit_intent
                    exit_reason = (
                        f'Trailing stop (trending_up LONG): '
                        f'price {current_price:.2f} <= trail {self.trailing_stop_price:.2f} '
                        f'(high {self.highest_price_since_entry:.2f}, '
                        f'entry {self.entry_price:.2f}, day {self.bars_in_position})'
                    )

            elif self.entry_pathway == 'trending_down_short':
                # Trailing stop (SHORT): price rises above trailing stop
                if self.trailing_activated and current_price >= self.trailing_stop_price:
                    should_exit = True
                    intent = exit_intent
                    exit_reason = (
                        f'Trailing stop (trending_down SHORT): '
                        f'price {current_price:.2f} >= trail {self.trailing_stop_price:.2f} '
                        f'(low {self.lowest_price_since_entry:.2f}, '
                        f'entry {self.entry_price:.2f}, day {self.bars_in_position})'
                    )

            elif self.entry_pathway == 'ranging_long':
                # Profit target: price reaches target level
                if current_price >= self.profit_target_price:
                    should_exit = True
                    intent = exit_intent
                    exit_reason = (
                        f'Profit target (ranging LONG): '
                        f'price {current_price:.2f} >= target {self.profit_target_price:.2f} '
                        f'(entry {self.entry_price:.2f}, day {self.bars_in_position})'
                    )

            else:
                # Indicator reversal pathways: ranging SHORT, trending_up SHORT, trending_down LONG, volatile SHORT
                reversal = self._check_indicator_reversal(macd_hist, ad, natr, sma)
                if reversal is not None:
                    should_exit = True
                    intent = exit_intent
                    exit_reason = reversal

        # ---- Tertiary: Time-based backstop (pathway-specific) ----
        if not should_exit:
            backstop = self._get_pathway_backstop()
            if self.bars_in_position >= backstop:
                should_exit = True
                intent = exit_intent
                exit_reason = (
                    f'Time backstop ({self.entry_pathway}): '
                    f'bars {self.bars_in_position} >= max {backstop}'
                )

        if not should_exit:
            exit_reason = self._build_holding_reason(
                current_price, macd_hist, ad, natr, sma
            )

        bars_since_entry = self.bars_in_position
        final_entry_pathway = self.entry_pathway
        final_stop_price = self.stop_price
        if should_exit:
            self._reset_state()

        output = ExitSignalOutput(
            should_exit=should_exit,
            exit_reason=exit_reason,
            position_size=abs(position.size),
            bars_since_entry=bars_since_entry,
            intent=intent,
            macd_histogram_value=macd_hist,
            ad_value=ad,
            natr_value=natr,
            sma_value=sma,
            current_price=current_price,
            entry_pathway=final_entry_pathway,
            stop_price=final_stop_price
        )

        self.log_exit_output(output)
        return output

    def _check_indicator_reversal(self, macd_hist: float, ad: float,
                                  natr: float, sma: float):
        """Check indicator reversal for reversal pathways. Returns exit_reason or None."""
        pw = self.entry_pathway
        day = self.bars_in_position
        checks = {
            'ranging_short': ('macd_histogram', macd_hist, self.entry_macd_histogram_threshold, '<', '.2f'),
            'trending_up_short': ('ad', ad, self.entry_ad_threshold, '<', '.0f'),
            'trending_down_long': ('natr', natr, self.entry_natr_threshold, '<', '.4f'),
            'volatile_short': ('sma', sma, self.entry_sma_threshold, '<', '.2f'),
        }
        if pw not in checks:
            return None
        name, val, thresh, cmp, fmt = checks[pw]
        triggered = (val < thresh) if cmp == '<' else (val > thresh)
        if triggered:
            return (f'Indicator reversal ({pw}): {name} {val:{fmt}} {cmp} '
                    f'threshold {thresh:{fmt}} (day {day})')
        return None

    def _initialize_exit_levels(self) -> None:
        """Initialize trailing stop or profit target for non-reversal pathways."""
        if self.entry_pathway == 'trending_up_long':
            self.highest_price_since_entry = self.entry_price
            self.trailing_activated = False
            self.trailing_stop_price = None
        elif self.entry_pathway == 'trending_down_short':
            self.lowest_price_since_entry = self.entry_price
            self.trailing_activated = False
            self.trailing_stop_price = None
        elif self.entry_pathway == 'ranging_long':
            atr_val = self.get_indicator(f'atr_{self.exit_atr_period}')
            self.profit_target_price = self.entry_price + (atr_val * self.exit_profit_target_atr_mult_ranging_long)

    def _update_trailing_stop(self, current_price: float) -> None:
        """Update trailing stop for trailing-stop pathways (LONG and SHORT)."""
        atr_value = self.get_indicator(f'atr_{self.exit_atr_period}')
        if self.entry_pathway == 'trending_up_long':
            # LONG trailing: track highest price, trail below
            if current_price > self.highest_price_since_entry:
                self.highest_price_since_entry = current_price

            activation_level = self.entry_price + (self.exit_trailing_activation_atr_mult * atr_value)

            if not self.trailing_activated:
                if self.highest_price_since_entry >= activation_level:
                    self.trailing_activated = True
                    self.trailing_stop_price = self.highest_price_since_entry - (self.exit_trailing_atr_multiplier * atr_value)
            else:
                # Ratchet upward only: max(new_trail, previous_trail)
                new_trail = self.highest_price_since_entry - (self.exit_trailing_atr_multiplier * atr_value)
                if new_trail > self.trailing_stop_price:
                    self.trailing_stop_price = new_trail

        elif self.entry_pathway == 'trending_down_short':
            # SHORT trailing: track lowest price, trail above
            if current_price < self.lowest_price_since_entry:
                self.lowest_price_since_entry = current_price

            activation_level = self.entry_price - (self.exit_trailing_activation_atr_mult * atr_value)

            if not self.trailing_activated:
                if self.lowest_price_since_entry <= activation_level:
                    self.trailing_activated = True
                    self.trailing_stop_price = self.lowest_price_since_entry + (self.exit_trailing_atr_multiplier * atr_value)
            else:
                # Ratchet downward only: min(new_trail, previous_trail)
                new_trail = self.lowest_price_since_entry + (self.exit_trailing_atr_multiplier * atr_value)
                if new_trail < self.trailing_stop_price:
                    self.trailing_stop_price = new_trail

    def _detect_entry_pathway(self, position) -> None:
        """Detect entry pathway from market regime and position direction."""
        regime = self.get_market_regime()
        is_long = position.direction == 'LONG'

        if regime == 'ranging':
            self.entry_pathway = 'ranging_long' if is_long else 'ranging_short'
        elif regime == 'trending_up':
            self.entry_pathway = 'trending_up_long' if is_long else 'trending_up_short'
        elif regime == 'trending_down':
            self.entry_pathway = 'trending_down_long' if is_long else 'trending_down_short'
        elif regime == 'volatile':
            self.entry_pathway = 'volatile_short'
        else:
            raise ValueError(f"Unknown market regime '{regime}' in _detect_entry_pathway")

    def _compute_stop_price(self) -> None:
        """Compute pathway-specific hard stop price at trade entry (frozen for duration)."""
        atr_value = self.get_indicator(f'atr_{self.exit_atr_period}')

        if self.entry_pathway == 'ranging_short':
            self.stop_price = self.entry_price + (atr_value * _STOP_ATR_RANGING)
        elif self.entry_pathway == 'trending_up_short':
            self.stop_price = self.entry_price + (atr_value * _STOP_ATR_TRENDING_UP)
        elif self.entry_pathway == 'trending_down_long':
            self.stop_price = self.entry_price - (atr_value * _STOP_ATR_TRENDING_DOWN)
        elif self.entry_pathway == 'trending_down_short':
            self.stop_price = self.entry_price + (atr_value * _STOP_ATR_TRENDING_DOWN)
        elif self.entry_pathway == 'volatile_short':
            self.stop_price = self.entry_price + (atr_value * self.exit_hard_stop_atr_mult_volatile_short)
        elif self.entry_pathway == 'trending_up_long':
            self.stop_price = self.entry_price - (atr_value * self.exit_hard_stop_atr_mult_trending_up_long)
        elif self.entry_pathway == 'ranging_long':
            self.stop_price = self.entry_price - (atr_value * _STOP_ATR_RANGING_LONG)

    def _get_pathway_backstop(self) -> int:
        """Return the time backstop for the current entry pathway."""
        if self.entry_pathway == 'trending_down_long':
            return self.exit_time_backstop_trending_down_long
        elif self.entry_pathway == 'trending_down_short':
            return self.exit_time_backstop_trending_down_short
        elif self.entry_pathway == 'trending_up_long':
            return self.exit_time_backstop_trending_up_long
        elif self.entry_pathway == 'ranging_long':
            return self.exit_time_backstop_ranging_long
        elif self.entry_pathway == 'volatile_short':
            return self.exit_time_backstop_volatile_short
        else:
            return self.exit_time_backstop_default

    def _build_holding_reason(self, current_price: float,
                              macd_hist: float, ad: float,
                              natr: float, sma: float) -> str:
        """Build diagnostic holding reason based on active pathway."""
        backstop = self._get_pathway_backstop()
        base = f'Holding {self.entry_pathway} (day {self.bars_in_position}/{backstop}): '
        if self.entry_pathway in ('trending_up_long', 'trending_down_short'):
            is_long_trail = self.entry_pathway == 'trending_up_long'
            trail_status = 'ACTIVE' if self.trailing_activated else 'PENDING'
            atr_val = self.get_indicator(f'atr_{self.exit_atr_period}')
            extreme = self.highest_price_since_entry if is_long_trail else self.lowest_price_since_entry
            extreme_label = 'high' if is_long_trail else 'low'
            sign = 1 if is_long_trail else -1
            activation_level = self.entry_price + (sign * self.exit_trailing_activation_atr_mult * atr_val)
            trail_detail = (f'trail_stop {self.trailing_stop_price:.2f}'
                            if self.trailing_activated
                            else f'activation_level {activation_level:.2f}')
            return (f'{base}trailing {trail_status}, {extreme_label} {extreme:.2f}, '
                    f'{trail_detail}, price {current_price:.2f}, hard_stop {self.stop_price:.2f}')
        elif self.entry_pathway == 'ranging_long':
            return (f'{base}profit_target {self.profit_target_price:.2f}, '
                    f'price {current_price:.2f}, hard_stop {self.stop_price:.2f}')
        # Indicator reversal pathways: show holding condition (inverse of exit trigger)
        indicator_map = {
            'ranging_short': ('macd_histogram', macd_hist, self.entry_macd_histogram_threshold, '.2f', '>='),
            'trending_up_short': ('ad', ad, self.entry_ad_threshold, '.0f', '>='),
            'trending_down_long': ('natr', natr, self.entry_natr_threshold, '.4f', '>='),
            'volatile_short': ('sma', sma, self.entry_sma_threshold, '.2f', '>='),
        }
        if self.entry_pathway in indicator_map:
            name, val, thresh, fmt, hold_cmp = indicator_map[self.entry_pathway]
            return (f'{base}{name} {val:{fmt}} {hold_cmp} threshold {thresh:{fmt}}, '
                    f'price {current_price:.2f}, stop {self.stop_price:.2f}')
        return f'Holding unknown pathway (day {self.bars_in_position}): price {current_price:.2f}'

    def _reset_state(self) -> None:
        """Reset all per-trade state variables to initial values."""
        self.bars_in_position = 0
        self.entry_pathway = None
        self.entry_price = None
        self.stop_price = None
        self.highest_price_since_entry = None
        self.lowest_price_since_entry = None
        self.trailing_stop_price = None
        self.trailing_activated = False
        self.profit_target_price = None

    def _get_component_specific_state(self) -> Dict[str, Any]:
        """Return exit-specific state for live trading persistence."""
        return {
            'bars_in_position': self.bars_in_position,
            'entry_pathway': self.entry_pathway,
            'entry_price': self.entry_price,
            'stop_price': self.stop_price,
            'highest_price_since_entry': self.highest_price_since_entry,
            'lowest_price_since_entry': self.lowest_price_since_entry,
            'trailing_stop_price': self.trailing_stop_price,
            'trailing_activated': self.trailing_activated,
            'profit_target_price': self.profit_target_price
        }

    def _restore_component_specific_state(self, state: Dict[str, Any]) -> None:
        """Restore exit-specific state from persistence."""
        self.bars_in_position = state['bars_in_position']
        self.entry_pathway = state['entry_pathway']
        self.entry_price = state['entry_price']
        self.stop_price = state['stop_price']
        self.highest_price_since_entry = state['highest_price_since_entry']
        self.lowest_price_since_entry = state['lowest_price_since_entry']
        self.trailing_stop_price = state['trailing_stop_price']
        self.trailing_activated = state['trailing_activated']
        self.profit_target_price = state['profit_target_price']
