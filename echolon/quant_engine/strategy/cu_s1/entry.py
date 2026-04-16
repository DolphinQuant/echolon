"""
Entry Component - Eight-Pathway Momentum/Mean-Reversion Strategy

Business Logic Source: workspace/current/strategy/entry_prompt.md

Pathways: 1=ranging LONG(MFI), 2=trending_up LONG(SAR+ADX confirm), 3=trending_down SHORT(OBV),
  4=trending_down LONG(NATR spike), 5=volatile LONG(ADX), 6=volatile SHORT(ADXR),
  7=trending_up SHORT(MINUS_DM), 8=ranging SHORT(WILLR)

Indicators: Tier1: mfi_{period}, adx_{period}, natr_{period}, willr_{period}
  Tier2: sar, adxr, minus_dm | Tier3: obv | market_regime via get_market_regime()

HYP_002: OBV z-score (sigma-normalized change) replaces absolute OBV for stationarity
HYP_001/HYP_003: Custom SAR (accel=0.02, max=0.3) matching ta-lib accel with raised cap
Pathway 2 modification: ADX confirmation filter addresses SAR IC decay (-195.6%)
Pathway 8 (NEW): WILLR overbought → ranging SHORT expansion (50.4% regime time, 0 prior SHORT trades)
"""

from ...core.base.base_component import BaseComponent
from ...core.interfaces.trading_interfaces import ITradingEngine
from ...types import EntrySignalOutput, OrderIntent

# Rolling window for OBV z-score computation (HYP_002: stationarity fix)
# 20-bar window provides stable rolling statistics for daily SHFE data
OBV_ZSCORE_WINDOW = 20

# Number of historical bars used to initialise Wilder's SAR (50 gives stable warmup)
SAR_LOOKBACK = 50

# Fixed WILLR period (standard Williams %R, no optimizable period param)
WILLR_PERIOD = 14


class entry_rule(BaseComponent):
    """
    Eight-pathway entry component for SHFE copper futures (interday).

    Generates LONG and SHORT signals across four distinct market regimes:
      1. RANGING LONG          : MFI oversold mean-reversion (37 trades, 81.1% WR, PF 10.11)
      2. TRENDING_UP LONG      : SAR + ADX confirmation trend-following (ADX filters SAR IC decay)
      3. TRENDING_DOWN SHORT   : OBV z-score continuation (HYP_002: sigma-normalized, 47.4% WR)
      4. TRENDING_DOWN LONG    : NATR volatility spike rebound (3 trades, 66.7% WR, PF 19.18)
      5. VOLATILE LONG         : ADX strength expansion (2 trades, 50.0% WR, PF 11.20)
      6. VOLATILE SHORT        : ADXR trend-exhaustion (4 trades, 100.0% WR, PF Inf)
      7. TRENDING_UP SHORT     : minus_dm counter-trend exhaustion (6 trades, 66.7% WR, PF 2.49)
      8. RANGING SHORT         : WILLR overbought mean-reversion (30 trades, 63.3% WR, PF 3.10)
    """

    def __init__(self, trading_engine: ITradingEngine, **params):
        super().__init__(trading_engine, **params)

        # --- Tier 1 indicator periods ---
        self.mfi_period = self.params['entry_mfi_period']
        self.adx_period = self.params['entry_adx_period']
        self.natr_period = self.params['entry_natr_period']

        # --- Threshold parameters ---
        self.mfi_oversold_threshold = self.params['entry_mfi_oversold_threshold']
        self.adx_confirmation_threshold = self.params['entry_adx_confirmation_threshold']
        self.obv_threshold = self.params['entry_obv_threshold']
        self.adx_threshold = self.params['entry_adx_threshold']
        self.minus_dm_threshold = self.params['entry_minus_dm_threshold']
        self.adxr_threshold = self.params['entry_adxr_threshold']
        self.natr_threshold = self.params['entry_natr_threshold']
        self.willr_overbought_threshold = self.params['entry_willr_overbought_threshold']

        # --- SAR parameters (FIXED per C9.3 REVERT pattern) ---
        self.sar_accel_factor = self.params['entry_sar_accel_factor']
        self.sar_max_accel = self.params['entry_sar_max_accel']

        # --- Fixed direction parameters ---
        self.entry_direction_regime_1 = self.params['entry_direction_regime_1']    # 'LONG' ranging
        self.entry_direction_regime_2 = self.params['entry_direction_regime_2']    # 'LONG' trending_up
        self.entry_direction_regime_3 = self.params['entry_direction_regime_3']    # 'SHORT' trending_down
        self.entry_direction_regime_4 = self.params['entry_direction_regime_4']    # 'LONG' trending_down NATR
        self.entry_direction_regime_5 = self.params['entry_direction_regime_5']    # 'LONG' volatile
        self.entry_direction_regime_6 = self.params['entry_direction_regime_6']    # 'SHORT' volatile
        self.entry_direction_regime_7 = self.params['entry_direction_regime_7']    # 'SHORT' ranging
        self.entry_direction_regime_8 = self.params['entry_direction_regime_8']    # 'SHORT' trending_up counter-trend

        self.log(
            f"entry_rule init: entry_mfi_period={self.mfi_period}, "
            f"entry_adx_period={self.adx_period}, "
            f"entry_natr_period={self.natr_period}, "
            f"entry_mfi_oversold_threshold={self.mfi_oversold_threshold}, "
            f"entry_adx_confirmation_threshold={self.adx_confirmation_threshold}, "
            f"entry_obv_threshold(sigma)={self.obv_threshold}, "
            f"entry_adx_threshold={self.adx_threshold}, "
            f"entry_minus_dm_threshold={self.minus_dm_threshold}, "
            f"entry_adxr_threshold={self.adxr_threshold}, "
            f"entry_natr_threshold={self.natr_threshold}, "
            f"entry_willr_overbought_threshold={self.willr_overbought_threshold}, "
            f"obv_zscore_window={OBV_ZSCORE_WINDOW}, "
            f"entry_sar_accel_factor={self.sar_accel_factor}, "
            f"entry_sar_max_accel={self.sar_max_accel}, "
            f"sar_lookback={SAR_LOOKBACK}"
        )

    def _compute_custom_sar(self) -> float:
        """Compute Wilder's Parabolic SAR with params from strategy_params (accel=0.02, max=0.3)."""
        required_bars = SAR_LOOKBACK + 1
        # Build high/low series oldest→newest over required_bars bars
        highs = [self.get_high(ago) for ago in range(required_bars - 1, -1, -1)]
        lows = [self.get_low(ago) for ago in range(required_bars - 1, -1, -1)]

        # Initialise: determine initial trend direction from first two bars
        is_uptrend = highs[1] >= highs[0]

        if is_uptrend:
            ep = highs[0]
            sar = lows[0]
        else:
            ep = lows[0]
            sar = highs[0]

        af = self.sar_accel_factor

        for i in range(1, len(highs)):
            prev_sar = sar
            prev_ep = ep
            prev_af = af

            if is_uptrend:
                # In uptrend: SAR trails below price
                new_sar = prev_sar + prev_af * (prev_ep - prev_sar)
                # SAR cannot be above the two prior lows
                if i >= 2:
                    new_sar = min(new_sar, lows[i - 1], lows[i - 2])
                else:
                    new_sar = min(new_sar, lows[i - 1])
                # Check for reversal
                if lows[i] < new_sar:
                    is_uptrend = False
                    sar = prev_ep          # SAR becomes highest EP of prior uptrend
                    ep = lows[i]
                    af = self.sar_accel_factor
                else:
                    sar = new_sar
                    if highs[i] > prev_ep:
                        ep = highs[i]
                        af = min(prev_af + self.sar_accel_factor, self.sar_max_accel)
            else:
                # In downtrend: SAR trails above price
                new_sar = prev_sar + prev_af * (prev_ep - prev_sar)
                # SAR cannot be below the two prior highs
                if i >= 2:
                    new_sar = max(new_sar, highs[i - 1], highs[i - 2])
                else:
                    new_sar = max(new_sar, highs[i - 1])
                # Check for reversal
                if highs[i] > new_sar:
                    is_uptrend = True
                    sar = prev_ep          # SAR becomes lowest EP of prior downtrend
                    ep = highs[i]
                    af = self.sar_accel_factor
                else:
                    sar = new_sar
                    if lows[i] < prev_ep:
                        ep = lows[i]
                        af = min(prev_af + self.sar_accel_factor, self.sar_max_accel)

        return sar

    def _compute_obv_zscore(self) -> float:
        """Compute sigma-normalized OBV change z-score over OBV_ZSCORE_WINDOW bars."""
        # Need window+1 bars: window changes require window+1 OBV values
        required_bars = OBV_ZSCORE_WINDOW + 1
        obv_series = self.get_indicator_series('obv', required_bars)

        # Compute 1-bar OBV changes: changes[i] = obv_series[i+1] - obv_series[i]
        changes = [obv_series[i + 1] - obv_series[i] for i in range(len(obv_series) - 1)]

        rolling_mean = sum(changes) / len(changes)
        variance = sum((c - rolling_mean) ** 2 for c in changes) / len(changes)
        rolling_std = variance ** 0.5

        if rolling_std == 0.0:
            return 0.0

        # Current OBV change = most recent change (last element)
        current_change = changes[-1]
        return (current_change - rolling_mean) / rolling_std

    def generate_signal(self) -> EntrySignalOutput:
        """Generate entry signal across 8 pathways based on market regime."""
        # --- Gather market context (interday: get_market_regime()) ---
        regime = self.get_market_regime()

        # --- Read indicator values ---
        mfi_value = self.get_indicator(f'mfi_{self.mfi_period}')
        sar_value = self._compute_custom_sar()
        obv_value = self.get_indicator('obv')
        adx_value = self.get_indicator(f'adx_{self.adx_period}')
        minus_dm_value = self.get_indicator('minus_dm')
        adxr_value = self.get_indicator('adxr')
        natr_value = self.get_indicator(f'natr_{self.natr_period}')
        willr_value = self.get_indicator(f'willr_{WILLR_PERIOD}')
        close_price = self.get_current_price()

        # --- Compute OBV z-score for Pathway 3 (HYP_002: stationarity fix) ---
        obv_zscore = self._compute_obv_zscore()

        # --- Initialise output defaults ---
        signal = 'HOLD'
        intent = None
        strength = 0.0
        entry_reason = ''

        # Pathway 1: RANGING LONG – MFI oversold mean-reversion (81.1% WR, PF 10.11)
        # Pathway 8: RANGING SHORT – WILLR overbought mean-reversion (63.3% WR, PF 3.10)
        if regime == 'ranging':
            if mfi_value < self.mfi_oversold_threshold:
                signal = self.entry_direction_regime_1      # 'LONG'
                intent = OrderIntent.ENTRY_LONG
                depth = self.mfi_oversold_threshold - mfi_value
                strength = min(1.0, depth / self.mfi_oversold_threshold)
                entry_reason = (
                    f"Pathway 1 (ranging) mean-reversion LONG: "
                    f"MFI {mfi_value:.2f} < threshold {self.mfi_oversold_threshold:.1f} "
                    f"(oversold signal, depth={depth:.2f})"
                )
            elif willr_value > self.willr_overbought_threshold:
                signal = self.entry_direction_regime_7      # 'SHORT'
                intent = OrderIntent.ENTRY_SHORT
                # Strength proportional to elevation above threshold (scale: distance to 0)
                elevation = willr_value - self.willr_overbought_threshold
                strength = min(1.0, elevation / abs(-100.0 - self.willr_overbought_threshold))
                entry_reason = (
                    f"Pathway 8 (ranging) WILLR overbought SHORT: "
                    f"WILLR {willr_value:.2f} > threshold {self.willr_overbought_threshold:.1f} "
                    f"(IC=-0.103 overbought mean-reversion, elevation={elevation:.2f})"
                )
            else:
                entry_reason = (
                    f"Pathway 1/8 (ranging): MFI {mfi_value:.2f} >= threshold "
                    f"{self.mfi_oversold_threshold:.1f} AND WILLR {willr_value:.2f} <= threshold "
                    f"{self.willr_overbought_threshold:.1f} — no entry condition met"
                )

        # Pathway 2: TRENDING_UP LONG – SAR + ADX confirmation (addresses SAR IC decay -195.6%)
        # Pathway 7: TRENDING_UP SHORT – minus_dm counter-trend (66.7% WR, PF 2.49)
        elif regime == 'trending_up':
            if close_price > sar_value and adx_value > self.adx_confirmation_threshold:
                signal = self.entry_direction_regime_2      # 'LONG'
                intent = OrderIntent.ENTRY_LONG
                # Strength modulated by ADX confirmation strength
                adx_strength_scale = 50.0 - self.adx_confirmation_threshold
                adx_factor = min(1.0, (adx_value - self.adx_confirmation_threshold) / adx_strength_scale) if adx_strength_scale > 0 else 1.0
                strength = min(1.0, 1.0 * adx_factor)
                entry_reason = (
                    f"Pathway 2 (trending_up) SAR+ADX confirmation LONG: "
                    f"close {close_price:.2f} > SAR {sar_value:.2f} "
                    f"AND ADX {adx_value:.2f} > confirmation {self.adx_confirmation_threshold:.1f} "
                    f"(adx_factor={adx_factor:.3f}, strength={strength:.3f})"
                )
            elif minus_dm_value > self.minus_dm_threshold:
                signal = self.entry_direction_regime_8      # 'SHORT' trending_up counter-trend
                intent = OrderIntent.ENTRY_SHORT
                elevation = minus_dm_value - self.minus_dm_threshold
                strength = min(1.0, elevation / self.minus_dm_threshold)
                entry_reason = (
                    f"Pathway 7 (trending_up) counter-trend exhaustion SHORT: "
                    f"MINUS_DM {minus_dm_value:.2f} > threshold {self.minus_dm_threshold:.1f} "
                    f"(bearish momentum elevated, elevation={elevation:.2f})"
                )
            else:
                entry_reason = (
                    f"Pathway 2/7 (trending_up): close {close_price:.2f} <= SAR {sar_value:.2f} "
                    f"OR ADX {adx_value:.2f} <= confirmation {self.adx_confirmation_threshold:.1f} "
                    f"AND MINUS_DM {minus_dm_value:.2f} <= threshold {self.minus_dm_threshold:.1f} "
                    f"— no entry condition met"
                )

        # Pathway 3: TRENDING_DOWN SHORT – OBV z-score continuation (HYP_002, 47.4% WR)
        # Pathway 4: TRENDING_DOWN LONG – NATR spike rebound (66.7% WR, PF 19.18)
        elif regime == 'trending_down':
            if obv_zscore < self.obv_threshold:
                signal = self.entry_direction_regime_3      # 'SHORT'
                intent = OrderIntent.ENTRY_SHORT
                depth = self.obv_threshold - obv_zscore
                strength = min(1.0, depth / 3.0)
                entry_reason = (
                    f"Pathway 3 (trending_down) trend-continuation SHORT: "
                    f"OBV_zscore {obv_zscore:.3f} < threshold {self.obv_threshold:.3f} sigma "
                    f"(HYP_002 stationary, raw_obv={obv_value:.0f}, depth={depth:.3f})"
                )
            elif natr_value > self.natr_threshold:
                signal = self.entry_direction_regime_4      # 'LONG'
                intent = OrderIntent.ENTRY_LONG
                spike = natr_value - self.natr_threshold
                strength = min(1.0, spike / self.natr_threshold)
                entry_reason = (
                    f"Pathway 4 (trending_down) NATR volatility spike LONG: "
                    f"NATR {natr_value:.3f} > threshold {self.natr_threshold:.2f} "
                    f"(panic-selling exhaustion rebound, spike={spike:.3f})"
                )
            else:
                entry_reason = (
                    f"Pathway 3/4 (trending_down): OBV_zscore {obv_zscore:.3f} >= threshold "
                    f"{self.obv_threshold:.3f} sigma AND NATR {natr_value:.3f} <= threshold "
                    f"{self.natr_threshold:.2f} — no entry condition met "
                    f"(raw_obv={obv_value:.0f})"
                )

        # Pathway 5: VOLATILE LONG – ADX strength expansion (50.0% WR, PF 11.20)
        # Pathway 6: VOLATILE SHORT – ADXR trend-exhaustion (100.0% WR, PF Inf)
        elif regime == 'volatile':
            if adx_value > self.adx_threshold:
                signal = self.entry_direction_regime_5      # 'LONG'
                intent = OrderIntent.ENTRY_LONG
                max_elevation = 100.0 - self.adx_threshold
                elevation = adx_value - self.adx_threshold
                strength = min(1.0, elevation / max_elevation) if max_elevation > 0 else 1.0
                entry_reason = (
                    f"Pathway 5 (volatile) ADX expansion LONG: "
                    f"ADX {adx_value:.2f} > threshold {self.adx_threshold:.1f} "
                    f"(trend strength confirmation, elevation={elevation:.2f})"
                )
            elif adxr_value < self.adxr_threshold:
                signal = self.entry_direction_regime_6      # 'SHORT'
                intent = OrderIntent.ENTRY_SHORT
                depth = self.adxr_threshold - adxr_value
                strength = min(1.0, depth / self.adxr_threshold)
                entry_reason = (
                    f"Pathway 6 (volatile) ADXR trend-exhaustion SHORT: "
                    f"ADXR {adxr_value:.2f} < threshold {self.adxr_threshold:.1f} "
                    f"(absence of directional strength, depth={depth:.2f})"
                )
            else:
                entry_reason = (
                    f"Pathway 5/6 (volatile): ADX {adx_value:.2f} <= threshold {self.adx_threshold:.1f} "
                    f"AND ADXR {adxr_value:.2f} >= threshold {self.adxr_threshold:.1f} "
                    f"— no entry condition met"
                )

        # All other regimes → HOLD
        else:
            entry_reason = (
                f"Regime '{regime}' not targeted by strategy "
                f"(targets: ranging, trending_up, trending_down, volatile) — HOLD"
            )

        output = EntrySignalOutput(
            signal=signal,
            strength=strength,
            type=f'entry_{signal.lower()}' if signal != 'HOLD' else 'hold',
            entry_reason=entry_reason,
            intent=intent,
            regime=regime,
            mfi_value=mfi_value,
            sar_value=sar_value,
            close_price=close_price,
            obv_value=obv_value,
            adx_value=adx_value,
            minus_dm_value=minus_dm_value,
            adxr_value=adxr_value,
            natr_value=natr_value,
            willr_value=willr_value
        )

        self.log_entry_output(output)
        return output
