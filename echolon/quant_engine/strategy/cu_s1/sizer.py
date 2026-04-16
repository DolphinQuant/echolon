"""
Position Sizer Component - PROTECTIVE Scope (8-Pathway Regime Strategy)
========================================================================

Implements Fixed Percentage Risk sizing for SHFE copper futures (interday/daily).

Business Logic Source: workspace/current/strategy/sizer_prompt.md

Sizing Formula:
    risk_amount = equity × risk_per_trade_pct / 100
    stop_distance = trailing_atr_multiplier × ATR(atr_period)
    risk_per_contract = stop_distance × contract_multiplier
    raw_size = risk_amount / risk_per_contract

Marginal Rounding (trade starvation prevention):
    If marginal_rounding_threshold ≤ raw_size < 1.0 → round UP to 1 lot
    Rationale: At p75 ATR, raw_size=0.845; marginal rounding rescues these
    signals. Without this, ~25%+ of valid entry signals are blocked.
    Feasibility: median_atr_raw_size=1.055, p75_atr_raw_size=0.845.

Position Constraint:
    Maximum 1 contract per trade (single-position framework).

Coherence with Exit:
    Uses identical atr_period as exit component (shared parameter, default 20).
    trailing_atr_multiplier in sizing (FIXED 2.437) is intentionally lower than
    primary exit stops (3.0–4.0× per regime). This deliberate risk underestimation
    ensures raw_size >= 1.0 at median ATR while accepting that actual stop
    distances may be wider than the sizing assumption.

Scope: Uniform across all eight pathways (ranging LONG via MFI, trending_up LONG
    via SAR+ADX, trending_down SHORT via OBV, volatile LONG via ADX,
    trending_up SHORT via MINUS_DM, volatile SHORT via ADXR,
    trending_down LONG via NATR, ranging SHORT via WILLR).
    No explicit regime variation in sizing logic; max_position_lots=1 cap ensures
    consistent 1-lot execution across all regimes. Ranging SHORT pathway inherits
    identical sizing treatment—regime-agnostic and direction-agnostic architecture.

Parameters (from strategy_params.py SizerParameters):
    - atr_period: INT [14, 20] default 20 (shared with exit component for ATR coherence)
    - risk_per_trade_pct: FIXED = 8.5 (load-bearing infrastructure per preservation mandate)
    - trailing_atr_multiplier: FIXED = 2.437
    - marginal_rounding_threshold: Float in [0.3, 0.6] (default 0.406)
    - contract_multiplier: FIXED = 5 (SHFE copper, 5 tons per contract)
    - max_position_lots: FIXED = 1 (OOS stability guard—expansion forbidden)

Volatility Adjustment: Disabled (uniform fixed sizing per sizer_prompt.md spec)
"""

from ...core.base.base_component import BaseComponent
from ...core.interfaces.trading_interfaces import ITradingEngine
from ...types import EntrySignalOutput, SizerOutput


class position_sizer(BaseComponent):
    """
    Fixed Percentage Risk position sizer for PROTECTIVE 8-Pathway Regime Strategy.

    Sizes LONG and SHORT positions uniformly based on:
    - Portfolio equity and fixed risk percentage (8.5%)
    - ATR-derived stop distance (trailing_atr_multiplier FIXED 2.437)
    - SHFE copper contract multiplier (5 tons/contract)
    - Marginal rounding rescue for near-1-lot signals during elevated volatility
      (threshold 0.406; p75 raw_size=0.845, median raw_size=1.055)

    Applies identically to all eight pathways: ranging LONG (MFI), trending_up LONG (SAR+ADX),
    trending_down SHORT (OBV), volatile LONG (ADX), trending_up SHORT (MINUS_DM),
    volatile SHORT (ADXR), trending_down LONG (NATR), ranging SHORT (WILLR).
    No explicit regime branching in sizing logic. No volatility adjustment applied
    (uniform fixed sizing per spec).
    """

    def __init__(self, trading_engine: ITradingEngine, **params):
        super().__init__(trading_engine, **params)

        # Extract parameters via direct access (no error handling per policy)
        self.atr_period = self.params['atr_period']
        self.risk_per_trade_pct = self.params['risk_per_trade_pct']
        self.trailing_atr_multiplier = self.params['trailing_atr_multiplier']
        self.marginal_rounding_threshold = self.params['marginal_rounding_threshold']
        self.max_position_lots = self.params['max_position_lots']
        self.contract_multiplier = self.params['contract_multiplier']

        self.log(
            f"position_sizer initialized: risk_pct={self.risk_per_trade_pct:.2f}%, "
            f"atr_period={self.atr_period}, "
            f"trailing_atr_mult={self.trailing_atr_multiplier}, "
            f"max_position_lots={self.max_position_lots}, "
            f"contract_mult={self.contract_multiplier}, "
            f"marginal_threshold={self.marginal_rounding_threshold}"
        )

    def calculate_size(self, signal_data: EntrySignalOutput) -> SizerOutput:
        """
        Calculate position size using Fixed Percentage Risk methodology.

        Steps:
        1. Compute risk_amount from portfolio equity and risk_per_trade_pct
        2. Compute stop_distance from ATR(atr_period) and trailing_atr_multiplier
        3. Compute risk_per_contract = stop_distance × contract_multiplier
        4. Compute raw_size = risk_amount / risk_per_contract
        5. Apply marginal rounding if threshold ≤ raw_size < 1.0
        6. Cap at max_position_lots = 1
        7. Validate and convert to non-negative integer

        Args:
            signal_data: EntrySignalOutput from entry component (attribute access)

        Returns:
            SizerOutput with calculated_size (int), signal_direction, sizing_reason,
            raw_size (float), and diagnostic fields
        """
        signal_direction = signal_data.signal

        # --- Step 1: Get portfolio equity ---
        equity = self.portfolio.get_total_value()

        # --- Step 2: Get ATR for stop distance (Tier 1 indicator: name_period) ---
        atr = self.get_indicator(f'atr_{self.atr_period}')

        # --- Step 3: Compute risk amount ---
        # Per-trade dollar risk = equity × risk_pct / 100
        risk_amount = equity * self.risk_per_trade_pct / 100.0

        # --- Step 4: Compute per-contract risk ---
        # stop_distance = trailing_atr_multiplier × ATR
        # risk_per_contract = stop_distance × contract_multiplier (tons/contract)
        stop_distance = self.trailing_atr_multiplier * atr
        risk_per_contract = stop_distance * self.contract_multiplier

        # --- Step 5: Compute raw position size ---
        raw_size = risk_amount / risk_per_contract

        # --- Step 6: Apply sizing adjustments ---
        # Marginal rounding: rescue near-1-lot signals during elevated volatility.
        # When threshold ≤ raw_size < 1.0, round UP to 1 lot to prevent trade starvation.
        marginal_rounded = False
        if raw_size >= self.marginal_rounding_threshold and raw_size < 1.0:
            adjusted_size = 1.0
            marginal_rounded = True
            sizing_reason = (
                f'Marginal rounding: raw_size={raw_size:.4f} >= '
                f'threshold={self.marginal_rounding_threshold:.2f} → 1 lot | '
                f'equity={equity:.0f}, atr={atr:.4f}, '
                f'stop_dist={stop_distance:.4f}, '
                f'risk_per_contract={risk_per_contract:.4f}, '
                f'risk_amount={risk_amount:.2f}'
            )

        # Cap at max_position_lots (single-position framework constraint per sizer_prompt.md)
        elif raw_size > self.max_position_lots:
            adjusted_size = float(self.max_position_lots)
            sizing_reason = (
                f'Capped at max {self.max_position_lots} lot(s): raw_size={raw_size:.4f} | '
                f'equity={equity:.0f}, risk_pct={self.risk_per_trade_pct:.2f}%, '
                f'atr={atr:.4f}, stop_dist={stop_distance:.4f}, '
                f'risk_per_contract={risk_per_contract:.4f}, '
                f'risk_amount={risk_amount:.2f}'
            )

        else:
            # raw_size < marginal_rounding_threshold: insufficient for rounding → 0 lots
            adjusted_size = raw_size
            sizing_reason = (
                f'Fixed risk sizing: raw_size={raw_size:.4f} '
                f'(below threshold={self.marginal_rounding_threshold:.2f}) | '
                f'equity={equity:.0f}, risk_pct={self.risk_per_trade_pct:.2f}%, '
                f'atr={atr:.4f}, stop_dist={stop_distance:.4f}, '
                f'risk_per_contract={risk_per_contract:.4f}, '
                f'risk_amount={risk_amount:.2f}'
            )

        # --- Step 7: Validate and convert to non-negative integer ---
        calculated_size = self.validate_and_convert_position_size(adjusted_size)

        # --- Construct output with diagnostic fields ---
        output = SizerOutput(
            calculated_size=calculated_size,
            signal_direction=signal_direction,
            sizing_reason=sizing_reason,
            raw_size=raw_size,
            # Diagnostic extra fields (allowed via extra='allow')
            equity=equity,
            atr_value=atr,
            stop_distance=stop_distance,
            risk_per_contract=risk_per_contract,
            risk_amount=risk_amount,
            adjusted_size=adjusted_size,
            marginal_rounded=marginal_rounded,
            atr_period=self.atr_period,
            trailing_atr_multiplier=self.trailing_atr_multiplier,
            max_position_lots=self.max_position_lots,
            contract_multiplier=self.contract_multiplier,
            risk_per_trade_pct=self.risk_per_trade_pct,
            marginal_rounding_threshold=self.marginal_rounding_threshold
        )

        self.log_sizer_output(output)
        return output
