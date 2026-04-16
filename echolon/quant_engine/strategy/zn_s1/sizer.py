"""
Sizer Component - Fixed Percentage Risk Position Sizing
========================================================

Implements fixed percentage risk position sizing for SHFE zinc futures
across all pathways (ranging LONG/SHORT, trending_up LONG/SHORT,
trending_down LONG/SHORT, volatile SHORT). Uniform sizing applies to
all regimes including the trending_up LONG cascade extension.

- Risk per trade = equity x risk_per_trade_pct / 100
- Stop distance estimated from ATR(exit_atr_period) x trailing_atr_multiplier (synthetic risk estimate)
- Risk per contract = stop_distance x contract_multiplier (5 tons/lot for SHFE zinc)
- Marginal rounding rescue for fractional lots (prevents trade starvation)
- Hard cap at max_position_lots=2 (fixed constant, not an optimizable parameter)

Business Logic Source:
    workspace/current/strategy/sizer_prompt.md

Indicator Naming:
    - atr_{atr_period}: Tier 1 indicator (Average True Range, shared from exit component)

Shared Parameters (from strategy_params.py SizerParameters):
    - exit_atr_period: shared from exit component, INT range [12, 14], default 13
    - trailing_atr_multiplier: shared from exit component, FLOAT range [2.0, 3.5], default 2.20

Own Parameters (from strategy_params.py SizerParameters):
    - risk_per_trade_pct: FLOAT range [5.5, 6.5], default 5.8
      Break-even risk_pct = 5.47%; lower bound 5.5% ensures executability
      without marginal rounding dependency given zinc ATR ~382, multiplier=5, capital=100k
    - marginal_rounding_threshold: FLOAT range [0.3, 0.7], default 0.34

Fixed Constants (hardcoded, not in SizerParameters):
    - contract_multiplier=5: SHFE zinc futures, 5 tons/lot (instrument-specific constant)
    - max_position_lots=2: hard position cap (infrastructure constant)

Coherence Note:
    trailing_atr_multiplier (shared from exit, default 2.20) is used for synthetic
    sizing-risk estimation, matching exit component's trailing stop distance.
"""

import math

from ...core.base.base_component import BaseComponent
from ...core.interfaces.trading_interfaces import ITradingEngine
from ...types import SizerOutput, EntrySignalOutput


class position_sizer(BaseComponent):
    """
    Fixed Percentage Risk Position Sizer for SHFE zinc futures.

    Uniform sizing applies across all seven pathways including the
    trending_up LONG cascade extension. No pathway-specific variations.

    Calculates position size based on:
    1. Per-trade dollar risk = equity x risk_per_trade_pct / 100
    2. Synthetic stop distance = ATR(exit_atr_period) x trailing_atr_multiplier
    3. Per-contract risk = stop_distance x contract_multiplier
    4. Raw lots = dollar_risk / per_contract_risk
    5. Apply marginal rounding rescue for fractional lots
    6. Cap at max_position_lots=2 (fixed constant per sizer_prompt.md)

    Feasibility validation (from sizer_prompt.md):
        break_even_risk_pct=5.47%; optimized_raw_size=1.39 at default 5.8%;
        marginal rounding at threshold 0.34 prevents starvation for edge cases.

    Fixed Constants (hardcoded, not in SizerParameters):
        contract_multiplier=5: SHFE zinc, 5 tons/lot
        max_position_lots=2: hard cap per sizer_prompt.md
    """

    def __init__(self, trading_engine: ITradingEngine, **params):
        super().__init__(trading_engine, **params)

        # Shared parameters from exit component
        self.atr_period = self.params['exit_atr_period']
        self.sizing_atr_multiplier = self.params['trailing_atr_multiplier']

        # Sizer parameters
        self.risk_per_trade_pct = self.params['risk_per_trade_pct']
        self.marginal_rounding_threshold = self.params['marginal_rounding_threshold']

        # Fixed constants - NOT in SizerParameters (instrument-specific infrastructure)
        self.max_position_lots = 2       # Hard cap: 2 lots per sizer_prompt.md "fixed" section
        self.contract_multiplier = 5     # SHFE zinc: 5 tons/lot (fixed instrument constant)

    def calculate_size(self, signal_data: EntrySignalOutput) -> SizerOutput:
        """
        Calculate position size using fixed percentage risk model.

        Formula:
            raw_size = (equity x risk_per_trade_pct / 100) /
                       (ATR(atr_period) x trailing_atr_multiplier x contract_multiplier)

        Steps:
            1. If signal is HOLD, return zero size immediately
            2. Calculate per-trade dollar risk from current equity
            3. Calculate synthetic stop distance from ATR x sizing_atr_multiplier
            4. Calculate risk per contract using contract_multiplier
            5. Derive raw lot size = dollar_risk / per_contract_risk
            6. Apply marginal rounding rescue for sub-lot sizes
            7. Enforce max_position_lots cap
            8. Validate and return SizerOutput

        Args:
            signal_data: EntrySignalOutput from entry component (attribute access)

        Returns:
            SizerOutput with calculated_size, signal_direction, sizing_reason, raw_size
        """
        signal_direction = signal_data.signal

        # Step 1: No sizing needed for HOLD signals
        if signal_direction == 'HOLD':
            output = SizerOutput(
                calculated_size=0,
                signal_direction='HOLD',
                sizing_reason='No position sizing needed: signal is HOLD',
                raw_size=0.0,
            )
            self.log_sizer_output(output)
            return output

        # Step 2: Calculate per-trade dollar risk from current equity
        current_equity = self.portfolio.get_total_value()
        dollar_risk = current_equity * self.risk_per_trade_pct / 100.0

        # Step 3: Calculate synthetic stop distance using ATR x sizing_atr_multiplier
        # ATR(atr_period) is in absolute price units (RMB/ton) for zinc futures
        current_price = self.get_current_price()
        atr = self.get_indicator(f'atr_{self.atr_period}')
        stop_distance = atr * self.sizing_atr_multiplier

        # Step 4: Calculate risk per contract using contract_multiplier
        # CRITICAL for futures: risk_per_contract = stop_distance x multiplier
        # For SHFE zinc: multiplier = 5 tons/lot
        risk_per_contract = stop_distance * self.contract_multiplier

        # Step 5: Calculate raw lot size
        raw_size = dollar_risk / risk_per_contract

        # Step 6: Apply marginal rounding rescue
        # When 0 < raw_size < 1.0 and raw_size >= threshold, round up to 1 lot
        # Prevents trade starvation during low-volatility periods or capital drawdowns
        if raw_size < 1.0 and raw_size >= self.marginal_rounding_threshold:
            rounded_size = 1.0
            rounding_applied = True
        else:
            rounded_size = math.floor(raw_size)
            rounding_applied = False

        # Step 7: Enforce max_position_lots cap (fixed at 2 lots)
        capped_size = min(rounded_size, self.max_position_lots)

        # Build sizing reason with full diagnostic detail
        sizing_reason = (
            f'Fixed % risk: equity={current_equity:.0f}, '
            f'risk_pct={self.risk_per_trade_pct:.2f}%, '
            f'dollar_risk={dollar_risk:.0f}, '
            f'ATR({self.atr_period})={atr:.2f}, '
            f'sizing_atr_mult={self.sizing_atr_multiplier:.1f}, '
            f'stop_dist={stop_distance:.2f}, '
            f'multiplier={self.contract_multiplier}, '
            f'risk_per_contract={risk_per_contract:.2f}, '
            f'raw_lots={raw_size:.3f}'
        )

        if rounding_applied:
            sizing_reason += (
                f', marginal_rounding: {raw_size:.3f} >= '
                f'threshold {self.marginal_rounding_threshold:.2f} -> 1 lot'
            )

        sizing_reason += f', final_size={int(capped_size)}'

        # Step 8: Validate and convert to non-negative integer
        validated_size = self.validate_and_convert_position_size(capped_size)

        output = SizerOutput(
            calculated_size=validated_size,
            signal_direction=signal_direction,
            sizing_reason=sizing_reason,
            raw_size=raw_size,
            current_equity=current_equity,
            dollar_risk=dollar_risk,
            atr_value=atr,
            stop_distance=stop_distance,
            risk_per_contract=risk_per_contract,
            contract_multiplier=self.contract_multiplier,
            rounding_applied=rounding_applied,
            current_price=current_price,
        )

        self.log_sizer_output(output)
        return output
