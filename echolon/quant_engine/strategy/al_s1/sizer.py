"""
Position Sizer Component - Inverse Volatility Risk-Based Sizing with Regime-Aware Stop Selection

Sizing Method: Percentage Risk with ATR-based Volatility Scaling.
Formula: raw_size = (portfolio_value x risk_per_trade_pct/100) / (atr x selected_stop_mult x contract_multiplier)

Regime-Conditional Stop Selection (8 pathways, all sourced from exit-shared parameters):
  - trending_up LONG:    exit_trending_up_long_stop_mult (shared from exit)
  - trending_up SHORT:   exit_trending_up_short_stop_mult (shared from exit)
  - trending_down LONG:  exit_trending_down_long_stop_mult (shared from exit, FLOAT optimizable)
  - trending_down SHORT: exit_trending_down_short_stop_mult (shared from exit, FLOAT optimizable)
  - ranging LONG:        exit_ranging_long_stop_mult (shared from exit)
  - ranging SHORT:       exit_ranging_short_stop_mult (shared from exit)
  - volatile LONG:       exit_volatile_long_stop_mult (shared from exit)
  - volatile SHORT:      exit_volatile_short_stop_mult (shared from exit)

Stop Distance: ATR x selected_stop_mult (shared ATR infrastructure with exit)

Marginal Rounding: Futures contract indivisibility rescue.
  - When raw_size >= marginal_rounding_threshold AND raw_size < 1.0 -> round up to 1 lot
  - When raw_size < marginal_rounding_threshold -> block trade (size = 0)

Constraints:
  - Max position: [5.0, 8.0] lots (FLOAT, optimizable)
  - Contract multiplier: 5 (SHFE Aluminum, 5 tons/lot)

Parameters (sizer-owned):
  - risk_per_trade_pct: [1.8, 2.5] FLOAT
  - marginal_rounding_threshold: [0.3, 0.7] FLOAT
  - max_position_lots: [5.0, 8.0] FLOAT
  - volatile_regime_size_floor: [2.5, 4.5] FLOAT (min lots for volatile regime)
  - exit_atr_period: [10, 30] INT (shared from exit)
  - contract_multiplier: 5 (FIXED)
  - exit_*_stop_mult: 8 shared stop multiplier parameters from exit component
"""

from ...core.base.base_component import BaseComponent
from ...core.interfaces.trading_interfaces import ITradingEngine
from ...types import SizerOutput, EntrySignalOutput


class position_sizer(BaseComponent):
    """
    Inverse Volatility Risk-Based position sizer for SHFE Aluminum futures.

    Calculates position size based on a fixed percentage of portfolio equity
    at risk per trade, using ATR-based stop distance and contract multiplier.
    Stop multipliers are sourced from exit-shared parameters to ensure position
    size matches actual stop distance used by exit component. Implements marginal
    rounding to prevent trade starvation from contract indivisibility in futures
    with multiplier > 1.

    Eight regime-direction pathways (all parameter-sourced from exit):
      trending_up LONG / trending_down SHORT -> exit shared stop mults
      trending_down LONG -> exit_trending_down_long_stop_mult (optimizable)
      trending_down SHORT -> exit_trending_down_short_stop_mult (optimizable)
      ranging LONG -> exit_ranging_long_stop_mult
      ranging SHORT -> exit_ranging_short_stop_mult
      trending_up SHORT -> exit_trending_up_short_stop_mult
      volatile SHORT -> exit_volatile_short_stop_mult
      volatile LONG -> exit_volatile_long_stop_mult
    """

    def __init__(self, trading_engine: ITradingEngine, frequency_context=None, market_adapter=None, **params):
        super().__init__(trading_engine, frequency_context, market_adapter, **params)

        # Sizer-owned parameters
        self.risk_per_trade_pct = self.params['risk_per_trade_pct']
        self.marginal_rounding_threshold = self.params['marginal_rounding_threshold']
        self.volatile_regime_size_floor = self.params['volatile_regime_size_floor']

        # Fixed/structural parameters (shared from exit)
        self.atr_period = self.params['exit_atr_period']
        self.contract_multiplier = self.params['contract_multiplier']

        # Position constraints (FLOAT, optimizable [5.0, 8.0])
        self.max_position_size = self.params['max_position_lots']

        # Regime-specific stop multipliers (all shared from exit component)
        self.stop_mult_trending_up_long = self.params['exit_trending_up_long_stop_mult']
        self.stop_mult_trending_up_short = self.params['exit_trending_up_short_stop_mult']
        self.stop_mult_trending_down_long = self.params['exit_trending_down_long_stop_mult']
        self.stop_mult_trending_down_short = self.params['exit_trending_down_short_stop_mult']
        self.stop_mult_ranging_long = self.params['exit_ranging_long_stop_mult']
        self.stop_mult_ranging_short = self.params['exit_ranging_short_stop_mult']
        self.stop_mult_volatile_long = self.params['exit_volatile_long_stop_mult']
        self.stop_mult_volatile_short = self.params['exit_volatile_short_stop_mult']

    def _select_stop_multiplier(self, regime: str, direction: str) -> float:
        """
        Select regime-specific stop loss ATR multiplier.

        All multipliers are sourced from exit-shared parameters so that position
        size calculation uses the same stop distance as the exit component.
        Eight regime-direction pathways:
          1. trending_up + LONG:    exit_trending_up_long_stop_mult
          2. trending_up + SHORT:   exit_trending_up_short_stop_mult
          3. trending_down + LONG:  exit_trending_down_long_stop_mult
          4. trending_down + SHORT: exit_trending_down_short_stop_mult
          5. ranging + LONG:        exit_ranging_long_stop_mult
          6. ranging + SHORT:       exit_ranging_short_stop_mult
          7. volatile + LONG:       exit_volatile_long_stop_mult
          8. volatile + SHORT:      exit_volatile_short_stop_mult

        Args:
            regime: Market regime from entry signal ('trending_up', 'trending_down', 'ranging', 'volatile')
            direction: Trade direction ('LONG' or 'SHORT')

        Returns:
            Selected stop loss ATR multiplier
        """
        if regime == 'trending_up' and direction == 'LONG':
            return self.stop_mult_trending_up_long
        elif regime == 'trending_up' and direction == 'SHORT':
            return self.stop_mult_trending_up_short
        elif regime == 'trending_down' and direction == 'LONG':
            return self.stop_mult_trending_down_long
        elif regime == 'trending_down' and direction == 'SHORT':
            return self.stop_mult_trending_down_short
        elif regime == 'ranging' and direction == 'LONG':
            return self.stop_mult_ranging_long
        elif regime == 'ranging' and direction == 'SHORT':
            return self.stop_mult_ranging_short
        elif regime == 'volatile' and direction == 'LONG':
            return self.stop_mult_volatile_long
        elif regime == 'volatile' and direction == 'SHORT':
            return self.stop_mult_volatile_short
        else:
            return self.stop_mult_trending_up_long

    def calculate_size(self, signal_data: EntrySignalOutput) -> SizerOutput:
        """
        Calculate position size using Inverse Volatility Risk-Based model.

        Formula:
            risk_amount = portfolio_value x (sizer_risk_per_trade_pct / 100)
            selected_stop_mult = _select_stop_multiplier(regime, direction)
            stop_distance = ATR x selected_stop_mult
            risk_per_contract = stop_distance x contract_multiplier
            raw_size = risk_amount / risk_per_contract

        Final sizing logic:
            - raw_size >= max_position_lots: max_position_lots (cap)
            - raw_size >= 1.0: floor(raw_size) lots
            - raw_size >= marginal_rounding_threshold: 1 lot (rescue)
            - raw_size < marginal_rounding_threshold: 0 lots (blocked)

        Args:
            signal_data: EntrySignalOutput from entry component

        Returns:
            SizerOutput with calculated position size and diagnostics
        """
        signal_direction = signal_data.signal

        # Handle HOLD signal - no sizing needed
        if signal_direction == 'HOLD':
            output = SizerOutput(
                calculated_size=0,
                signal_direction='HOLD',
                sizing_reason='No sizing for HOLD signal',
                raw_size=0.0
            )
            self.log_sizer_output(output)
            return output

        # Gather market data and portfolio state
        portfolio_value = self.portfolio.get_total_value()
        atr = self.get_indicator(f'atr_{self.atr_period}')
        current_price = self.get_current_price()

        # Get regime from entry signal for regime-aware stop selection
        regime = signal_data.regime

        # Select regime-specific stop multiplier (parameter-sourced from exit)
        selected_stop_mult = self._select_stop_multiplier(regime, signal_direction)

        # Calculate risk amount: equity x risk percentage
        risk_amount = portfolio_value * (self.risk_per_trade_pct / 100.0)

        # Calculate stop distance using regime-specific ATR multiplier
        stop_distance = atr * selected_stop_mult

        # Calculate risk per contract WITH contract multiplier (CRITICAL for futures)
        # SHFE Aluminum: multiplier = 5 (5 tons/lot)
        risk_per_contract = stop_distance * self.contract_multiplier

        # Guard against zero/negative risk per contract
        if risk_per_contract <= 0:
            output = SizerOutput(
                calculated_size=0,
                signal_direction=signal_direction,
                sizing_reason=(
                    f'Zero risk per contract: stop_distance={stop_distance:.4f}, '
                    f'multiplier={self.contract_multiplier}. Trade blocked.'
                ),
                raw_size=0.0,
                portfolio_value=portfolio_value,
                risk_amount=risk_amount,
                risk_per_contract=risk_per_contract,
                atr_value=atr,
                stop_distance=stop_distance,
                current_price=current_price,
                regime=regime,
                selected_stop_mult=selected_stop_mult
            )
            self.log_sizer_output(output)
            return output

        # Core sizing formula
        raw_size = risk_amount / risk_per_contract

        # Volatile regime size floor: counteract inverse volatility penalty
        # High ATR in volatile regime causes undersizing of high-alpha trades
        volatile_floor_applied = False
        if regime == 'volatile' and raw_size < self.volatile_regime_size_floor:
            raw_size = self.volatile_regime_size_floor
            volatile_floor_applied = True

        # Apply final sizing logic per specification
        rounding_applied = False
        trade_blocked_by_rounding = False
        was_capped = False

        if raw_size >= self.max_position_size:
            # Cap at max position size
            final_size = float(self.max_position_size)
            was_capped = True
        elif raw_size >= 1.0:
            # Normal case: floor to whole contracts
            final_size = float(int(raw_size))
        elif raw_size >= self.marginal_rounding_threshold:
            # Marginal rescue: raw_size in [threshold, 1.0) -> round up to 1 lot
            final_size = 1.0
            rounding_applied = True
        else:
            # Below rescue threshold: block trade to prevent excessive risk
            final_size = 0.0
            trade_blocked_by_rounding = True

        # Validate and convert to non-negative integer (MANDATORY)
        validated_size = self.validate_and_convert_position_size(final_size)

        # Build sizing reason with full diagnostics
        stop_info = (
            f'ATR={atr:.2f} x stop_mult={selected_stop_mult} '
            f'(regime={regime}) x multiplier={self.contract_multiplier}'
        )

        if trade_blocked_by_rounding:
            sizing_reason = (
                f'Trade blocked by marginal rounding: raw_size={raw_size:.4f} < '
                f'threshold={self.marginal_rounding_threshold:.2f}. '
                f'Equity={portfolio_value:.0f}, risk={risk_amount:.2f} '
                f'({self.risk_per_trade_pct}%), '
                f'risk_per_contract={risk_per_contract:.2f} ({stop_info})'
            )
        elif rounding_applied:
            sizing_reason = (
                f'Marginal rounding applied: raw_size={raw_size:.4f} -> 1 lot. '
                f'Equity={portfolio_value:.0f}, risk={risk_amount:.2f} '
                f'({self.risk_per_trade_pct}%), '
                f'risk_per_contract={risk_per_contract:.2f} ({stop_info})'
            )
        elif was_capped:
            sizing_reason = (
                f'Position capped: raw_size={raw_size:.4f} -> max {self.max_position_size} lots. '
                f'Equity={portfolio_value:.0f}, risk={risk_amount:.2f} '
                f'({self.risk_per_trade_pct}%), '
                f'risk_per_contract={risk_per_contract:.2f} ({stop_info})'
            )
        else:
            volatile_note = f' [volatile floor={self.volatile_regime_size_floor:.1f} applied]' if volatile_floor_applied else ''
            sizing_reason = (
                f'Risk-based sizing: {validated_size} lots. '
                f'Equity={portfolio_value:.0f}, risk={risk_amount:.2f} '
                f'({self.risk_per_trade_pct}%), '
                f'risk_per_contract={risk_per_contract:.2f} ({stop_info}){volatile_note}'
            )

        output = SizerOutput(
            calculated_size=validated_size,
            signal_direction=signal_direction,
            sizing_reason=sizing_reason,
            raw_size=raw_size,
            portfolio_value=portfolio_value,
            risk_amount=risk_amount,
            risk_per_contract=risk_per_contract,
            atr_value=atr,
            stop_distance=stop_distance,
            multiplier=float(self.contract_multiplier),
            current_price=current_price,
            rounding_applied=rounding_applied,
            was_capped=was_capped,
            regime=regime,
            selected_stop_mult=selected_stop_mult
        )

        self.log_sizer_output(output)
        return output
