# Intraday Indicator Classification and Naming Convention

**Version**: 2.0
**Last Updated**: 2026-01-23
**Frequency**: Intraday (Sub-daily bars: 1m, 5m, 15m, 30m, 1h)
**Indicator Count**: 72 curated indicators

---

## Purpose

This document defines the **indicator system** for intraday trading strategies. It specifies:

1. **Classification**: Which indicators belong to which tier
2. **Session-Specific Indicators**: VWAP, opening range, session levels (UNIQUE to intraday)
3. **Time Features**: Session phase and bar position (UNIQUE to intraday)
4. **Period Calibration**: How to scale indicator periods for different bar sizes

**Authoritative Source**: `modules/indicators/config/intraday_analysis_indicators.json`

---

## Key Differences from Interday

| Aspect | Interday | Intraday |
|--------|----------|----------|
| Primary Filter | `market_regime` | `session_phase` |
| Context Layer | Trend-based regime | Volatility state |
| Session Indicators | N/A | VWAP, session levels, prev_session levels |
| Opening Range | N/A | OR breakout signals |
| Time Features | N/A | bar_of_day, session_phase |
| Removed Indicators | Full set | adxr, aroon_up, aroon_down, dx, ma, wma, var, tsf |

**Why Different?**
- Trend-based regime does NOT work for intraday (autocorrelation near zero, short signal persistence)
- Session structure (opening/closing behavior) is critical for intraday
- Noise-to-signal ratio is higher → prefer responsive indicators

---

## Three-Tier Indicator System

### Tier 1: Indicators with Lookback Periods (OPTIMIZABLE)

**Naming Convention**: `{name}_{period}` (lowercase) at runtime
**Optimization**: YES - single integer period parameter can be optimized

#### Available Indicators (19 total)

**Volatility Indicators (2)**:
- `ATR` - Average True Range
- `NATR` - Normalized Average True Range

**Momentum Indicators (10)**:
- `ADX` - Average Directional Index
- `PLUS_DI` - Plus Directional Indicator
- `MINUS_DI` - Minus Directional Indicator
- `AROONOSC` - Aroon Oscillator
- `CCI` - Commodity Channel Index
- `MFI` - Money Flow Index
- `MOM` - Momentum
- `ROC` - Rate of Change
- `RSI` - Relative Strength Index
- `WILLR` - Williams %R

**Moving Averages (3)**:
- `EMA` - Exponential Moving Average (preferred for intraday)
- `SMA` - Simple Moving Average
- `TEMA` - Triple Exponential Moving Average

**Statistics & Regression (1)**:
- `LINEARREG_SLOPE` - Linear Regression Slope

**Custom Indicators (2)**:
- `HIGHEST_HIGH` - Highest high over period
- `LOWEST_LOW` - Lowest low over period

**Statistics (1)**:
- `STDDEV` - Standard Deviation

#### Period Calibration by Bar Size

Indicator periods should be scaled based on bar size to maintain consistent look-back time:

| Bar Size | RSI | ATR | EMA_fast | EMA_slow | MACD |
|----------|-----|-----|----------|----------|------|
| 1m | 120 | 120 | 60 | 120 | 60/120/45 |
| 5m | 28 | 28 | 12 | 28 | 12/28/9 |
| 15m | 10 | 10 | 4 | 10 | 4/10/3 |
| 1h | 3 | 3 | 2 | 4 | 2/4/2 |

---

### Tier 2: Indicators with Special Parameters (NON-OPTIMIZABLE)

**Naming Convention**: `{name}` (lowercase, NO parameter suffix!)
**Optimization**: NO - use built-in defaults

#### Available Indicators (16 total)

**MACD Family (3)**:
- `MACD_LINE` - MACD line
- `MACD_SIGNAL` - MACD signal line
- `MACD_HISTOGRAM` - MACD histogram

**Stochastic Family (4)**:
- `STOCH_SLOWK` - Stochastic Slow %K
- `STOCH_SLOWD` - Stochastic Slow %D
- `STOCHRSI_FASTK` - Stochastic RSI Fast %K
- `STOCHRSI_FASTD` - Stochastic RSI Fast %D

**Bollinger Bands (2)** (raw bands moved to structural):
- `BBANDS_PCT_B` - Bollinger %B (position within bands, 0-1)
- `BBANDS_BANDWIDTH` - Bollinger Bandwidth (band width as % of middle)

**Keltner Channels (3)**:
- `KC_UPPER` - Keltner Channel upper (EMA + ATR × multiplier)
- `KC_LOWER` - Keltner Channel lower (EMA - ATR × multiplier)
- `KC_PCT_B` - Keltner %B (position within channels)

**Oscillators (2)**:
- `PRICE_ZSCORE` - Z-score of price vs moving average
- `VWAP_ZSCORE` - Z-score of price vs VWAP

**Other (2)**:
- `SAR` - Parabolic SAR
- `CMF` - Chaikin Money Flow

---

### Tier 3: Indicators without Lookback (NON-OPTIMIZABLE)

**Naming Convention**: `{name}` (lowercase)
**Optimization**: N/A - no parameters

#### Available Indicators (6 total)

**Volume Indicators (4)**:
- `AD` - Chaikin A/D Line
- `OBV` - On Balance Volume
- `ADOSC` - Accumulation/Distribution Oscillator
- `BOP` - Balance of Power

**Volatility (1)**:
- `TRANGE` - True Range

**Gap (1)**:
- `GAP_PCT` - Gap percentage from previous session close

---

## Session-Specific Indicators (UNIQUE TO INTRADAY)

These indicators are **system-provided** and reset each session. They provide critical context for intraday trading.

### Session Context (FREE - System Provided)

| Indicator | Purpose | Values |
|-----------|---------|--------|
| `session_phase` | Current session phase | Bar-size-dependent (see below) |
| `volatility_state` | ATR-based volatility level | 0 (low), 1 (normal), 2 (high) |
| `bar_of_session` | Bar number within session | Integer (varies by bar size) |
| `bars_remaining` | Bars until session close | Integer |

**Session Phase Values (Bar-Size-Dependent)**:
- **Granular (5m, 15m)**: `night`, `morning`, `afternoon` (+ non-tradeable: `morning_break`, `lunch_break`)
- **Aggregated (30m, 1h)**: `night_session`, `day_session`

Use `ctx.tradeable_phases` to get the correct phase list for your bar size.

### Session Indicators (11)

| Indicator | Purpose |
|-----------|---------|
| `vwap` | Volume-Weighted Average Price (institutional benchmark) |
| `vwap_distance_pct` | Percentage distance from VWAP |
| `vwap_zscore` | Z-score distance from VWAP (standard deviations) |
| `session_high` | Session high price |
| `session_low` | Session low price |
| `session_position_pct` | Position within session range (0-100%) |
| `volume_percentile` | Current bar volume percentile |
| `volume_vs_session_avg` | Current volume vs session average |
| `prev_session_close` | Previous session's closing price |
| `prev_session_high` | Previous session's high price |
| `prev_session_low` | Previous session's low price |

### Opening Range Indicators (5)

| Indicator | Purpose |
|-----------|---------|
| `night_or_high` | Night session opening range high |
| `night_or_low` | Night session opening range low |
| `day_or_high` | Day session opening range high |
| `day_or_low` | Day session opening range low |
| `or_breakout` | Opening range breakout signal (-1/0/1) |

### Pivot Points (4)

| Indicator | Purpose |
|-----------|---------|
| `pivot` | Central pivot point: (prev_high + prev_low + prev_close) / 3 |
| `pivot_r1` | First resistance: 2 × pivot - prev_low |
| `pivot_s1` | First support: 2 × pivot - prev_high |
| `pivot_distance_pct` | Percentage distance from pivot |

### Time Features (2)

| Indicator | Purpose |
|-----------|---------|
| `bar_of_day` | Bar number within trading day |
| `session_phase` | Current session phase (see above) |

---

## Intraday-Specific Context

### Primary Filter: Session Phase

For intraday strategies, `session_phase` is the PRIMARY filter controlling WHEN to trade:

```python
# Get tradeable phases from config (bar-size-aware)
tradeable_phases = ctx.tradeable_phases  # Dynamic list based on bar_size

IF session_phase IN tradeable_phases
AND bar_of_session > opening_buffer      # Avoid opening volatility (time-based)
AND bars_remaining > closing_buffer      # Leave room for exit (time-based)
AND [indicator] [comparison] [threshold] # Signal trigger
THEN ENTER
```

**Session Phase Values (Bar-Size-Dependent)**:
- **Granular (5m, 15m)**: `night`, `morning`, `afternoon`
- **Aggregated (30m, 1h)**: `night_session`, `day_session`

**Opening/Closing Buffers** (convert minutes to bars: buffer_bars = buffer_minutes / bar_size):
- Granular: `night`/`morning`/`afternoon` have separate buffer configs
- Aggregated: `night_session`/`day_session` use combined session buffers

**Non-Tradeable Phases** (granular only): `morning_break`, `lunch_break`

### Volatility State (Sizing Layer)

`volatility_state` controls HOW MUCH to risk, not when to trade:

| State | ATR Percentile | Action |
|-------|----------------|--------|
| 0 (low) | < 25th | Larger position, tighter stops |
| 1 (normal) | 25th-75th | Standard parameters |
| 2 (high) | > 75th | Smaller position, wider stops |

### Design Principle

- `session_phase` → Controls WHEN to trade (time filter)
- `volatility_state` → Controls HOW MUCH to risk (sizing)
- Technical indicators → Provide DIRECTION (entry signal)

**CRITICAL**: Do NOT use `market_regime` (trending_up/down) for intraday. It doesn't work (autocorrelation near zero, short signal persistence).

---

## Quick Reference Table

| Tier | Example | Runtime Name | Optimize? |
|------|---------|--------------|-----------|
| 1 (with_lookback) | ADX | `adx_14` | YES |
| 1 (with_lookback) | PLUS_DI | `plus_di_14` | YES |
| 1 (with_lookback) | RSI | `rsi_14` | YES |
| 2 (special_params) | MACD_LINE | `macd_line` | NO |
| 2 (special_params) | BBANDS_UPPER | `bbands_upper` | NO |
| 2 (special_params) | BBANDS_PCT_B | `bbands_pct_b` | NO |
| 2 (special_params) | KC_PCT_B | `kc_pct_b` | NO |
| 2 (special_params) | PRICE_ZSCORE | `price_zscore` | NO |
| 3 (without_lookback) | OBV | `obv` | N/A |
| 3 (without_lookback) | GAP_PCT | `gap_pct` | N/A |
| Session (FREE) | VWAP | `vwap` | N/A |
| Session (FREE) | Session Phase | `session_phase` | N/A |
| Session (FREE) | Pivot | `pivot` | N/A |
| Session (FREE) | Opening Range | `day_or_high` | N/A |

---

## Removed from Interday Set

These indicators were removed for intraday due to noise/lag issues:

| Indicator | Reason |
|-----------|--------|
| `adxr` | Too lagging - smooths already-smoothed ADX |
| `aroon_up`, `aroon_down` | Designed for longer timeframes (use `aroonosc` instead) |
| `dx` | Redundant with ADX |
| `ma`, `wma` | Prefer EMA for responsiveness |
| `var` | Redundant with stddev |
| `tsf` | Less reliable on noisy intraday data |
| `market_regime` | Trend-based regime doesn't work for intraday |

**Note**: `plus_di`, `minus_di`, `aroonosc` were added back in v2.0 for directional analysis.

---

## All 72 Intraday Indicators

**Technical (45)**:
```
atr, natr, adx, plus_di, minus_di, aroonosc, cci, mfi, mom, roc, rsi, willr,
ema, sma, dema, tema, linearreg_slope, highest_high, lowest_low, stddev,
trange, ad, obv, adosc, bop, cmf,
macd_line, macd_signal, macd_histogram, stoch_slowk, stoch_slowd,
stochrsi_fastk, stochrsi_fastd,
bbands_upper, bbands_middle, bbands_lower, bbands_pct_b, bbands_bandwidth,
kc_upper, kc_lower, kc_pct_b,
price_zscore, vwap_zscore, sar
```

**Session-Specific (27)**:
```
volatility_state, vwap, vwap_distance_pct, session_high, session_low,
session_position_pct, volume_percentile, volume_vs_session_avg,
prev_session_close, prev_session_high, prev_session_low, gap_pct,
night_or_high, night_or_low, day_or_high, day_or_low, or_breakout,
pivot, pivot_r1, pivot_s1, pivot_distance_pct,
bar_of_day, bars_remaining, total_bars_today, has_night_session,
bar_of_session, bars_remaining_in_session, session_bars_total, session_phase
```

---

## Usage Examples

### Entry with Session Filter and VWAP

```python
def generate_entry_signal(self) -> bool:
    # Session filter (WHEN to trade)
    session_phase = self.get_indicator('session_phase')
    bar_of_session = self.get_indicator('bar_of_session')
    bars_remaining = self.get_indicator('bars_remaining')

    # Use ctx.tradeable_phases for bar-size-aware phase list
    # Granular (5m/15m): ['night', 'morning', 'afternoon']
    # Aggregated (30m/1h): ['night_session', 'day_session']
    tradeable_phases = self.ctx.tradeable_phases
    if session_phase not in tradeable_phases:
        return False

    # Use phase-specific buffers from ctx.get_phase_buffers(session_phase)
    # or define adaptive logic based on session_phase
    opening_buffer = self.ctx.get_opening_buffer(session_phase)
    closing_buffer = self.ctx.get_closing_buffer(session_phase)
    if bar_of_session <= opening_buffer or bars_remaining <= closing_buffer:
        return False

    # VWAP reversion signal (DIRECTION)
    vwap_distance = self.get_indicator('vwap_distance_pct')
    if vwap_distance < -1.5:  # Price below VWAP
        return True  # Enter long toward VWAP

    return False
```

### Opening Range Breakout

```python
def generate_entry_signal(self) -> bool:
    session_phase = self.get_indicator('session_phase')
    bar_of_session = self.get_indicator('bar_of_session')

    # Determine which phase to use for ORB (day session start)
    # Granular: 'morning' is first day session phase
    # Aggregated: 'day_session' encompasses morning+afternoon
    day_session_phase = self.ctx.get_day_session_start_phase()  # or configure directly

    # ORB typically triggers after opening range forms (e.g., 30 min = bar 2 for 15m, bar 1 for 30m)
    orb_trigger_bar = self.ctx.minutes_to_bars(30)

    if session_phase != day_session_phase or bar_of_session != orb_trigger_bar:
        return False

    close = self.data.close[0]
    day_or_high = self.get_indicator('day_or_high')

    if close > day_or_high:  # Breakout above opening range
        return True

    return False
```
