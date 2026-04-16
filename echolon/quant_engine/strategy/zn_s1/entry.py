"""
Entry Component - Seven-Pathway Regime-Aware Entry Signal Generation

Implements seven regime-specific entry pathways for SHFE zinc futures on daily bars:
1. Ranging SHORT: Negative-IC macd_histogram entry (PRESERVED)
2. Ranging LONG: Positive-IC obv entry (PRESERVED)
3. Trending Up SHORT: Accumulation/Distribution ad entry (PRESERVED)
4. Trending Up LONG: minus_di entry (NEW - IC=+0.20 STRONG, sole positive IC in trending_up)
5. Trending Down SHORT: Momentum-following macd_signal entry (PRESERVED)
6. Trending Down LONG: Mean-reversion natr entry (PRESERVED)
7. Volatile SHORT: SMA mean-reversion entry (REDESIGNED - replaces degrading adxr pathway)

Market regime (SMA+ADX classification) acts as structural filter determining which
pathways are active. Dual-pathway regimes (ranging, trending_up, trending_down) evaluate
SHORT first, then LONG. Volatile has a single SHORT pathway (sma-based; adxr pathway
REMOVED after IC degradation: PF 1.06, recent 0.95).

Business Logic Source: workspace/current/strategy/entry_prompt.md
"""

from ...core.base.base_component import BaseComponent
from ...core.interfaces.trading_interfaces import ITradingEngine, OrderIntent
from ...types import EntrySignalOutput


class entry_rule(BaseComponent):
    """
    Seven-pathway regime-aware entry rule for SHFE zinc futures (interday).

    Pathway 1 - Ranging SHORT (PRESERVED):
        IF market_regime == 'ranging' AND macd_histogram > entry_macd_histogram_threshold
        THEN ENTER SHORT at next bar open.
        Rationale: Positive macd_histogram in ranging regime predicts lower future
        returns (IC = -0.148), signaling SHORT entry.

    Pathway 2 - Ranging LONG (PRESERVED):
        IF market_regime == 'ranging' AND obv > entry_obv_threshold
        THEN ENTER LONG at next bar open.
        Rationale: High OBV in ranging regime predicts higher future returns
        (IC = +0.147 STRONG), signaling volume-driven LONG entry.

    Pathway 3 - Trending Up SHORT (PRESERVED):
        IF market_regime == 'trending_up' AND ad > entry_ad_threshold
        THEN ENTER SHORT at next bar open.
        Rationale: High Accumulation/Distribution in uptrend predicts lower future
        returns (IC = -0.235 STRONG, stable). Volume-based indicator.

    Pathway 4 - Trending Up LONG (NEW):
        IF market_regime == 'trending_up' AND minus_di > entry_minus_di_threshold
        THEN ENTER LONG at next bar open.
        Rationale: Elevated minus_di in uptrend is sole positive IC factor (IC = +0.20,
        STRONG, symmetric tails), indicating LONG opportunity.

    Pathway 5 - Trending Down SHORT (PRESERVED):
        IF market_regime == 'trending_down' AND macd_signal > entry_macd_signal_threshold
        THEN ENTER SHORT at next bar open.
        Rationale: Elevated MACD signal line in downtrend indicates weakening
        momentum, favoring directional SHORT entry (IC = -0.258).

    Pathway 6 - Trending Down LONG (PRESERVED):
        IF market_regime == 'trending_down' AND natr > entry_natr_threshold
        THEN ENTER LONG at next bar open.
        Rationale: NATR IC=+0.425 (STRONG) indicates high volatility predicts
        positive returns. Mean-reversion LONG on volatility expansion captures
        bounce off downtrend slope. Critical 83.3% WR performance carrier.

    Pathway 7 - Volatile SHORT (REDESIGNED - replaces adxr):
        IF market_regime == 'volatile' AND sma > entry_sma_threshold
        THEN ENTER SHORT at next bar open.
        Rationale: SMA IC=-0.415 (STRONG, symmetric) replaces degrading adxr pathway
        (PF 1.06, recent 0.95). Stronger negative predictive correlation.

    Dual-pathway regimes (ranging, trending_up, trending_down) prioritize SHORT over LONG.
    No additional confirmation filter (baseline simplicity preserved).
    """

    # Strength normalization constants (computational, not trading logic parameters).
    # These scale raw indicator excess into [0.1, 1.0] signal strength range.
    # MACD histogram: approximate max expected excess for full strength (1.0)
    MACD_HISTOGRAM_STRENGTH_NORMALIZATION_DIVISOR = 40.0
    # OBV: approximate max expected obv excess for full strength (1.0)
    OBV_STRENGTH_NORMALIZATION_DIVISOR = 200000.0
    # AD: approximate max expected ad excess above threshold for full strength (1.0)
    AD_STRENGTH_NORMALIZATION_DIVISOR = 150000.0
    # MINUS_DI: ranges 0-100, threshold ~20.58, typical excess 0-30 → divisor 20
    MINUS_DI_STRENGTH_NORMALIZATION_DIVISOR = 20.0
    # NATR: normalize natr excess above threshold (natr > threshold for LONG entry)
    NATR_STRENGTH_NORMALIZATION_DIVISOR = 1.0
    # MACD signal: approximate max expected macd_signal excess for full strength (1.0)
    MACD_SIGNAL_STRENGTH_NORMALIZATION_DIVISOR = 100.0
    # SMA: zinc price scale ~18000-27000, threshold ~25000, excess up to ~2000+
    SMA_STRENGTH_NORMALIZATION_DIVISOR = 2000.0

    def __init__(self, trading_engine: ITradingEngine, **params):
        super().__init__(trading_engine, **params)

        # Extract entry parameters from params dict (no .get() with defaults)
        self.entry_minus_di_period = self.params['entry_minus_di_period']
        self.entry_sma_period = self.params['entry_sma_period']
        self.entry_ad_threshold = self.params['entry_ad_threshold']
        self.entry_macd_histogram_threshold = self.params['entry_macd_histogram_threshold']
        self.entry_minus_di_threshold = self.params['entry_minus_di_threshold']
        self.entry_sma_threshold = self.params['entry_sma_threshold']
        self.entry_obv_threshold = self.params['entry_obv_threshold']
        self.entry_natr_threshold = self.params['entry_natr_threshold']
        self.entry_macd_signal_threshold = self.params['entry_macd_signal_threshold']

    def generate_signal(self) -> EntrySignalOutput:
        """
        Generate entry signal based on seven-pathway regime-aware logic.

        Evaluates current market regime and applies the corresponding pathway(s):
        - ranging regime → check macd_histogram for SHORT, then obv for LONG
        - trending_up regime → check ad for SHORT, then minus_di for LONG
        - trending_down regime → check macd_signal for SHORT, then natr for LONG
        - volatile regime → check sma for SHORT entry
        - all other regimes → HOLD (no entry pathway defined)

        Dual-pathway regimes (ranging, trending_up, trending_down) prioritize SHORT over LONG.

        Returns:
            EntrySignalOutput with signal, strength, type, entry_reason, intent, regime
        """
        # Retrieve current market regime (Tier 3 - interday method)
        regime = self.get_market_regime()

        # Retrieve indicators
        # MACD histogram: Tier 2 indicator with special params (bare name)
        macd_histogram = self.get_indicator('macd_histogram')
        # OBV: Tier 3 indicator without lookback (bare name)
        obv = self.get_indicator('obv')
        # AD (Accumulation/Distribution): Tier 3 indicator without lookback (bare name)
        ad = self.get_indicator('ad')
        # MINUS_DI: Tier 1 indicator with parameterized period
        minus_di = self.get_indicator(f'minus_di_{self.entry_minus_di_period}')
        # NATR: Tier 1 indicator at fixed period 14 (entry_natr_period removed from params
        # per entry_prompt.md; period hardcoded to standard 14-day value)
        natr = self.get_indicator('natr_14')
        # MACD signal: Tier 2 indicator with special params (bare name)
        macd_signal = self.get_indicator('macd_signal')
        # SMA: Tier 1 indicator with parameterized period
        sma = self.get_indicator(f'sma_{self.entry_sma_period}')

        # Initialize defaults
        signal = 'HOLD'
        intent = None
        strength = 0.0
        signal_type = 'hold'
        entry_reason = ''

        # ----------------------------------------------------------------
        # Ranging regime: Pathway 1 (SHORT) then Pathway 2 (LONG)
        # ----------------------------------------------------------------
        if regime == 'ranging':
            # Pathway 1: Ranging SHORT (negative-IC macd_histogram) - PRESERVED
            # Positive macd_histogram predicts lower future returns. IC = -0.148.
            if macd_histogram > self.entry_macd_histogram_threshold:
                signal = 'SHORT'
                intent = OrderIntent.ENTRY_SHORT
                histogram_excess = macd_histogram - self.entry_macd_histogram_threshold
                strength = min(1.0, max(0.1, histogram_excess / self.MACD_HISTOGRAM_STRENGTH_NORMALIZATION_DIVISOR))
                signal_type = 'entry_short'
                entry_reason = (
                    f'Ranging SHORT: macd_histogram {macd_histogram:.2f} > '
                    f'threshold {self.entry_macd_histogram_threshold:.2f}, '
                    f'regime={regime}, negative-IC signal detected'
                )
            # Pathway 2: Ranging LONG (positive-IC obv) - PRESERVED
            # High OBV predicts higher future returns. IC = +0.147.
            elif obv > self.entry_obv_threshold:
                signal = 'LONG'
                intent = OrderIntent.ENTRY_LONG
                obv_excess = obv - self.entry_obv_threshold
                strength = min(1.0, max(0.1, obv_excess / self.OBV_STRENGTH_NORMALIZATION_DIVISOR))
                signal_type = 'entry_long'
                entry_reason = (
                    f'Ranging LONG: obv {obv:.0f} > '
                    f'threshold {self.entry_obv_threshold:.0f}, '
                    f'regime={regime}, positive-IC volume flow signal detected'
                )
            else:
                entry_reason = (
                    f'Ranging regime active but macd_histogram {macd_histogram:.2f} <= '
                    f'threshold {self.entry_macd_histogram_threshold:.2f} AND '
                    f'obv {obv:.0f} <= threshold {self.entry_obv_threshold:.0f}, no entry'
                )

        # ----------------------------------------------------------------
        # Trending Up regime: Pathway 3 (SHORT) then Pathway 4 (LONG)
        # ----------------------------------------------------------------
        elif regime == 'trending_up':
            # Pathway 3: Trending Up SHORT (Accumulation/Distribution) - PRESERVED
            # High AD in uptrend predicts lower future returns. IC = -0.235 STRONG.
            if ad > self.entry_ad_threshold:
                signal = 'SHORT'
                intent = OrderIntent.ENTRY_SHORT
                ad_excess = ad - self.entry_ad_threshold
                strength = min(1.0, max(0.1, ad_excess / self.AD_STRENGTH_NORMALIZATION_DIVISOR))
                signal_type = 'entry_short'
                entry_reason = (
                    f'Trending Up SHORT: ad {ad:.0f} > '
                    f'threshold {self.entry_ad_threshold:.0f}, '
                    f'regime={regime}, AD IC=-0.235 STRONG signal detected'
                )
            # Pathway 4: Trending Up LONG (minus_di) - NEW
            # Elevated minus_di in uptrend is sole positive IC factor (IC = +0.20 STRONG).
            elif minus_di > self.entry_minus_di_threshold:
                signal = 'LONG'
                intent = OrderIntent.ENTRY_LONG
                minus_di_excess = minus_di - self.entry_minus_di_threshold
                strength = min(1.0, max(0.1, minus_di_excess / self.MINUS_DI_STRENGTH_NORMALIZATION_DIVISOR))
                signal_type = 'entry_long'
                entry_reason = (
                    f'Trending Up LONG: minus_di {minus_di:.2f} > '
                    f'threshold {self.entry_minus_di_threshold:.2f}, '
                    f'regime={regime}, minus_di IC=+0.20 STRONG LONG signal detected'
                )
            else:
                entry_reason = (
                    f'Trending Up regime active but ad {ad:.0f} <= '
                    f'threshold {self.entry_ad_threshold:.0f} AND '
                    f'minus_di {minus_di:.2f} <= threshold {self.entry_minus_di_threshold:.2f}, no entry'
                )

        # ----------------------------------------------------------------
        # Trending Down regime: Pathway 5 (SHORT) then Pathway 6 (LONG)
        # ----------------------------------------------------------------
        elif regime == 'trending_down':
            # Pathway 5: Trending Down SHORT (macd_signal momentum) - PRESERVED
            # Elevated MACD signal in downtrend indicates weakening momentum.
            # IC = -0.258, favoring directional SHORT entry.
            if macd_signal > self.entry_macd_signal_threshold:
                signal = 'SHORT'
                intent = OrderIntent.ENTRY_SHORT
                macd_signal_excess = macd_signal - self.entry_macd_signal_threshold
                strength = min(1.0, max(0.1, macd_signal_excess / self.MACD_SIGNAL_STRENGTH_NORMALIZATION_DIVISOR))
                signal_type = 'entry_short'
                entry_reason = (
                    f'Trending Down SHORT: macd_signal {macd_signal:.2f} > '
                    f'threshold {self.entry_macd_signal_threshold:.2f}, '
                    f'regime={regime}, weakening momentum SHORT signal detected'
                )
            # Pathway 6: Trending Down LONG (mean-reversion natr) - PRESERVED
            # High NATR (volatility expansion) predicts positive future returns
            # (IC = +0.425 STRONG). Critical 83.3% WR performance carrier.
            elif natr > self.entry_natr_threshold:
                signal = 'LONG'
                intent = OrderIntent.ENTRY_LONG
                natr_excess = natr - self.entry_natr_threshold
                strength = min(1.0, max(0.1, natr_excess / self.NATR_STRENGTH_NORMALIZATION_DIVISOR))
                signal_type = 'entry_long'
                entry_reason = (
                    f'Trending Down LONG: natr {natr:.4f} > '
                    f'threshold {self.entry_natr_threshold:.4f}, '
                    f'regime={regime}, mean-reversion volatility expansion signal detected'
                )
            else:
                entry_reason = (
                    f'Trending Down regime active but macd_signal {macd_signal:.2f} <= '
                    f'threshold {self.entry_macd_signal_threshold:.2f} AND '
                    f'natr {natr:.4f} <= threshold {self.entry_natr_threshold:.4f}, no entry'
                )

        # ----------------------------------------------------------------
        # Pathway 7: Volatile SHORT (sma mean-reversion) - REDESIGNED
        # ----------------------------------------------------------------
        # SMA IC=-0.415 (STRONG, symmetric) replaces degrading adxr pathway
        # (adxr: PF 1.06, recent 0.95). Stronger negative predictive correlation.
        elif regime == 'volatile':
            if sma > self.entry_sma_threshold:
                signal = 'SHORT'
                intent = OrderIntent.ENTRY_SHORT
                sma_excess = sma - self.entry_sma_threshold
                strength = min(1.0, max(0.1, sma_excess / self.SMA_STRENGTH_NORMALIZATION_DIVISOR))
                signal_type = 'entry_short'
                entry_reason = (
                    f'Volatile SHORT: sma {sma:.2f} > '
                    f'threshold {self.entry_sma_threshold:.2f}, '
                    f'regime={regime}, SMA IC=-0.415 STRONG mean-reversion SHORT signal detected'
                )
            else:
                entry_reason = (
                    f'Volatile regime active but sma {sma:.2f} <= '
                    f'threshold {self.entry_sma_threshold:.2f}, no SHORT entry'
                )

        # ----------------------------------------------------------------
        # No pathway defined for other regimes
        # ----------------------------------------------------------------
        else:
            entry_reason = (
                f'No entry pathway for regime={regime}, '
                f'macd_histogram {macd_histogram:.2f}, ad {ad:.0f}, minus_di {minus_di:.2f}, '
                f'macd_signal {macd_signal:.2f}, natr {natr:.4f}, sma {sma:.2f}, '
                f'obv {obv:.0f}'
            )

        # Construct output BaseModel
        output = EntrySignalOutput(
            signal=signal,
            strength=strength,
            type=signal_type,
            entry_reason=entry_reason,
            intent=intent,
            regime=regime,
            # Strategy-specific diagnostic fields (extra='allow')
            macd_histogram_value=macd_histogram,
            obv_value=obv,
            ad_value=ad,
            minus_di_value=minus_di,
            natr_value=natr,
            macd_signal_value=macd_signal,
            sma_value=sma,
            entry_macd_histogram_threshold=self.entry_macd_histogram_threshold,
            entry_obv_threshold=self.entry_obv_threshold,
            entry_ad_threshold=self.entry_ad_threshold,
            entry_minus_di_threshold=self.entry_minus_di_threshold,
            entry_natr_threshold=self.entry_natr_threshold,
            entry_macd_signal_threshold=self.entry_macd_signal_threshold,
            entry_sma_threshold=self.entry_sma_threshold,
        )

        self.log_entry_output(output)
        return output
