"""
Entry Component - Bidirectional Regime Expansion Strategy

Generates entry signals across eight pathways at the daily bar horizon:

  Preserved Pathways:
    Pathway 1: Regime trending_up   -> aroonosc(16) > 12.0 -> LONG
    Pathway 2: Regime trending_up   -> trix(15) > entry_trix_trending_up_short_threshold -> SHORT (contrarian)
    Pathway 3: Regime ranging       -> macd_histogram > 0.1685 -> LONG (mean-reversion)
    Pathway 4: Regime ranging       -> tema(20) > entry_tema_ranging_short_threshold -> SHORT (contrarian)
    Pathway 6: Regime volatile      -> macd_histogram < entry_macd_histogram_volatile_long_threshold -> LONG (mean-reversion)
    Pathway 7: Regime volatile      -> ad > entry_ad_short_threshold -> SHORT
    Pathway 8: Regime trending_down -> atr(14) > entry_atr_trending_down_long_threshold
               AND mfi(14) > entry_mfi_trending_down_long_threshold -> LONG (contrarian mean-reversion)

  Redesigned Pathway:
    Pathway 5: Regime trending_down -> ppo > entry_ppo_trending_down_short_threshold -> SHORT (PPO-based)
"""

from ...core.base.base_component import BaseComponent
from ...core.interfaces.trading_interfaces import (
    ITradingEngine,
    OrderIntent,
)
from ...types import EntrySignalOutput


class entry_rule(BaseComponent):
    """
    Eight-pathway entry component covering all market regimes with bidirectional
    coverage in ranging, trending_up, trending_down, and volatile.

    Preserved pathways use Aroon Oscillator for uptrend LONG entries, MACD
    histogram mean-reversion for ranging LONG, TEMA contrarian for ranging SHORT,
    TRIX contrarian for trending_up SHORT, AD for volatile SHORT, and MACD
    histogram extreme negative tail for volatile LONG.

    Preserved trending_down LONG via ATR+MFI composite filter for mean-reversion
    bounce capture.

    Redesigned trending_down SHORT replaces degraded AD pathway with PPO
    (IC -0.175, negative tail IC -0.435) for improved short entry timing
    in falling markets.
    """

    def __init__(self, trading_engine: ITradingEngine, **params):
        super().__init__(trading_engine, **params)

        # Indicator periods (FIXED per params)
        self.aroonosc_period = self.params['aroonosc_period']
        self.tema_period = self.params['tema_period']
        self.trix_period = self.params['trix_period']
        self.atr_period = self.params['atr_14_period']
        self.mfi_period = self.params['mfi_14_period']

        # Entry thresholds (FIXED preserved values)
        self.aroonosc_long_threshold = self.params['aroonosc_long_threshold']
        self.macd_histogram_ranging_long_threshold = self.params['macd_histogram_ranging_long_threshold']
        self.entry_ad_short_threshold = self.params['entry_ad_short_threshold']
        self.entry_tema_ranging_short_threshold = self.params['entry_tema_ranging_short_threshold']
        self.entry_trix_trending_up_short_threshold = self.params['entry_trix_trending_up_short_threshold']
        self.entry_macd_histogram_volatile_long_threshold = self.params['entry_macd_histogram_volatile_long_threshold']
        self.entry_atr_trending_down_long_threshold = self.params['entry_atr_trending_down_long_threshold']
        self.entry_mfi_trending_down_long_threshold = self.params['entry_mfi_trending_down_long_threshold']

        # Redesigned trending_down SHORT threshold (FLOAT optimizable)
        self.entry_ppo_trending_down_short_threshold = self.params['entry_ppo_trending_down_short_threshold']

    def generate_signal(self) -> EntrySignalOutput:
        """
        Generate entry signal based on eight-pathway regime logic.

        Preserved Pathways:
            Pathway 1 (trending_up LONG): aroonosc > aroonosc_long_threshold
            Pathway 2 (trending_up SHORT): trix > entry_trix_trending_up_short_threshold
            Pathway 3 (ranging LONG): macd_histogram > macd_histogram_ranging_long_threshold
            Pathway 4 (ranging SHORT): tema > entry_tema_ranging_short_threshold
            Pathway 6 (volatile LONG): macd_histogram < entry_macd_histogram_volatile_long_threshold
            Pathway 7 (volatile SHORT): ad > entry_ad_short_threshold
            Pathway 8 (trending_down LONG): atr > entry_atr_trending_down_long_threshold
                AND mfi > entry_mfi_trending_down_long_threshold

        Redesigned Pathway:
            Pathway 5 (trending_down SHORT): ppo > entry_ppo_trending_down_short_threshold

        Returns:
            EntrySignalOutput with signal, strength, type, entry_reason, intent
        """
        # Get market regime (interday method)
        regime = self.get_market_regime()

        # Get indicator values
        # Tier 1: aroonosc with period
        aroonosc = self.get_indicator(f'aroonosc_{self.aroonosc_period}')

        # Tier 2: macd_histogram (special params, bare name)
        macd_histogram = self.get_indicator('macd_histogram')

        # Tier 1: tema with period
        tema = self.get_indicator(f'tema_{self.tema_period}')

        # Tier 1: trix with period
        trix = self.get_indicator(f'trix_{self.trix_period}')

        # Tier 3: ad without lookback (volatile SHORT only)
        ad = self.get_indicator('ad')

        # Tier 1: atr with period (trending_down LONG)
        atr = self.get_indicator(f'atr_{self.atr_period}')

        # Tier 1: mfi with period (trending_down LONG confirmation)
        mfi = self.get_indicator(f'mfi_{self.mfi_period}')

        # Tier 2: ppo (special params, bare name - trending_down SHORT)
        ppo = self.get_indicator('ppo')

        # Initialize defaults
        signal = 'HOLD'
        intent = None
        strength = 0.0
        signal_type = 'hold'
        reason = ''

        # Pathway 1 & 2: Trending Up (LONG via Aroon, SHORT via TRIX contrarian)
        if regime == 'trending_up':
            if aroonosc > self.aroonosc_long_threshold:
                # Pathway 1: LONG via Aroon Oscillator
                signal = 'LONG'
                intent = OrderIntent.ENTRY_LONG
                strength = min(1.0, (aroonosc - self.aroonosc_long_threshold) / max(1, 100 - self.aroonosc_long_threshold))
                signal_type = 'entry_long'
                reason = (
                    f'Trending Up regime: AroonOsc {aroonosc:.1f} > threshold {self.aroonosc_long_threshold} '
                    f'(preserved LONG, period {self.aroonosc_period})'
                )
            elif trix > self.entry_trix_trending_up_short_threshold:
                # Pathway 2: SHORT via TRIX contrarian
                signal = 'SHORT'
                intent = OrderIntent.ENTRY_SHORT
                strength = min(1.0, (trix - self.entry_trix_trending_up_short_threshold) / max(0.001, abs(self.entry_trix_trending_up_short_threshold)))
                signal_type = 'entry_short'
                reason = (
                    f'Trending Up regime: TRIX {trix:.6f} > threshold {self.entry_trix_trending_up_short_threshold:.4f} '
                    f'(preserved SHORT, period {self.trix_period})'
                )
            else:
                reason = (
                    f'Trending Up regime: AroonOsc {aroonosc:.1f} <= {self.aroonosc_long_threshold} '
                    f'and TRIX {trix:.6f} <= {self.entry_trix_trending_up_short_threshold:.4f} '
                    f'- no entry condition met'
                )

        # Pathway 5 & 8: Trending Down (SHORT via PPO, LONG via ATR+MFI composite)
        elif regime == 'trending_down':
            if atr > self.entry_atr_trending_down_long_threshold and mfi > self.entry_mfi_trending_down_long_threshold:
                # Pathway 8: LONG via ATR+MFI composite (contrarian mean-reversion)
                signal = 'LONG'
                intent = OrderIntent.ENTRY_LONG
                atr_excess = atr - self.entry_atr_trending_down_long_threshold
                mfi_excess = mfi - self.entry_mfi_trending_down_long_threshold
                strength = min(1.0, (atr_excess / max(0.01, self.entry_atr_trending_down_long_threshold) + mfi_excess / max(1, self.entry_mfi_trending_down_long_threshold)) / 2.0)
                signal_type = 'entry_long'
                reason = (
                    f'Trending Down regime: ATR {atr:.4f} > threshold {self.entry_atr_trending_down_long_threshold:.4f} '
                    f'AND MFI {mfi:.2f} > threshold {self.entry_mfi_trending_down_long_threshold:.2f} '
                    f'(preserved LONG, mean-reversion bounce)'
                )
            elif ppo > self.entry_ppo_trending_down_short_threshold:
                # Pathway 5: SHORT via PPO (redesigned, replaces AD)
                signal = 'SHORT'
                intent = OrderIntent.ENTRY_SHORT
                ppo_excess = ppo - self.entry_ppo_trending_down_short_threshold
                strength = min(1.0, ppo_excess / max(0.01, abs(self.entry_ppo_trending_down_short_threshold)))
                signal_type = 'entry_short'
                reason = (
                    f'Trending Down regime: PPO {ppo:.4f} > threshold {self.entry_ppo_trending_down_short_threshold:.4f} '
                    f'(redesigned SHORT, IC -0.175, negative tail IC -0.435)'
                )
            else:
                reason = (
                    f'Trending Down regime: ATR {atr:.4f} <= {self.entry_atr_trending_down_long_threshold:.4f} '
                    f'or MFI {mfi:.2f} <= {self.entry_mfi_trending_down_long_threshold:.2f} (no LONG); '
                    f'PPO {ppo:.4f} <= {self.entry_ppo_trending_down_short_threshold:.4f} (no SHORT) '
                    f'- no entry condition met'
                )

        # Pathway 3 & 4: Ranging (LONG via MACD histogram, SHORT via TEMA contrarian)
        elif regime == 'ranging':
            if macd_histogram > self.macd_histogram_ranging_long_threshold:
                # Pathway 3: LONG via MACD histogram mean-reversion
                signal = 'LONG'
                intent = OrderIntent.ENTRY_LONG
                strength = min(1.0, (macd_histogram - self.macd_histogram_ranging_long_threshold) / max(0.01, abs(self.macd_histogram_ranging_long_threshold)))
                signal_type = 'entry_long'
                reason = (
                    f'Ranging regime: MACD histogram {macd_histogram:.4f} > threshold '
                    f'{self.macd_histogram_ranging_long_threshold:.4f} '
                    f'(preserved LONG, mean-reversion)'
                )
            elif tema > self.entry_tema_ranging_short_threshold:
                # Pathway 4: SHORT via TEMA contrarian
                signal = 'SHORT'
                intent = OrderIntent.ENTRY_SHORT
                strength = min(1.0, (tema - self.entry_tema_ranging_short_threshold) / max(1, abs(self.entry_tema_ranging_short_threshold) * 0.1))
                signal_type = 'entry_short'
                reason = (
                    f'Ranging regime: TEMA {tema:.2f} > threshold {self.entry_tema_ranging_short_threshold:.2f} '
                    f'(preserved SHORT, period {self.tema_period})'
                )
            else:
                reason = (
                    f'Ranging regime: MACD histogram {macd_histogram:.4f} <= {self.macd_histogram_ranging_long_threshold:.4f} '
                    f'and TEMA {tema:.2f} <= {self.entry_tema_ranging_short_threshold:.2f} '
                    f'- no entry condition met'
                )

        # Pathway 6 & 7: Volatile (LONG via MACD histogram, SHORT via AD)
        elif regime == 'volatile':
            if macd_histogram < self.entry_macd_histogram_volatile_long_threshold:
                # Pathway 6: LONG via MACD histogram extreme negative tail
                signal = 'LONG'
                intent = OrderIntent.ENTRY_LONG
                macd_deficit = self.entry_macd_histogram_volatile_long_threshold - macd_histogram
                strength = min(1.0, macd_deficit / max(0.01, abs(self.entry_macd_histogram_volatile_long_threshold)))
                signal_type = 'entry_long'
                reason = (
                    f'Volatile regime: MACD histogram {macd_histogram:.4f} < threshold '
                    f'{self.entry_macd_histogram_volatile_long_threshold:.4f} '
                    f'(preserved LONG, mean-reversion)'
                )
            elif ad > self.entry_ad_short_threshold:
                # Pathway 7: SHORT via AD
                signal = 'SHORT'
                intent = OrderIntent.ENTRY_SHORT
                ad_excess = ad - self.entry_ad_short_threshold
                strength = min(1.0, abs(ad_excess) / max(1, abs(self.entry_ad_short_threshold) * 0.1)) if self.entry_ad_short_threshold != 0 else 0.5
                signal_type = 'entry_short'
                reason = (
                    f'Volatile regime: AD {ad:.0f} > threshold {self.entry_ad_short_threshold:.0f} '
                    f'(preserved SHORT)'
                )
            else:
                reason = (
                    f'Volatile regime: MACD histogram {macd_histogram:.4f} >= {self.entry_macd_histogram_volatile_long_threshold:.4f} '
                    f'and AD {ad:.0f} <= {self.entry_ad_short_threshold:.0f} '
                    f'- no entry condition met'
                )

        # Non-target regimes: no entry
        else:
            reason = (
                f'Non-target regime: {regime} '
                f'(active regimes: trending_up, trending_down, ranging, volatile). '
                f'AroonOsc={aroonosc:.1f}, MACD_hist={macd_histogram:.4f}, '
                f'TEMA={tema:.2f}, TRIX={trix:.6f}, AD={ad:.0f}, '
                f'ATR={atr:.4f}, MFI={mfi:.2f}, PPO={ppo:.4f}'
            )

        output = EntrySignalOutput(
            signal=signal,
            strength=strength,
            type=signal_type,
            entry_reason=reason,
            intent=intent,
            regime=regime,
            aroonosc_value=aroonosc,
            macd_histogram_value=macd_histogram,
            tema_value=tema,
            trix_value=trix,
            ad_value=ad,
            atr_value=atr,
            mfi_value=mfi,
            ppo_value=ppo,
        )

        self.log_entry_output(output)
        return output
