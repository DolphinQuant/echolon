# Intraday Indicators Catalog

**Total**: 72 indicators for intraday trading (sub-daily bars).

---

## 1. Indicator Catalog by Category

| Category | Count | Indicators |
|----------|-------|------------|
| Momentum | 6 | `rsi`, `cci`, `mfi`, `willr`, `mom`, `roc` |
| Trend | 7 | `adx`, `ema`, `sma`, `tema`, `plus_di`, `minus_di`, `aroonosc` |
| Volatility | 4 | `atr`, `natr`, `trange`, `stddev` |
| Price Channels | 10 | `highest_high`, `lowest_low`, `bbands_upper`, `bbands_middle`, `bbands_lower`, `bbands_pct_b`, `bbands_bandwidth`, `kc_upper`, `kc_lower`, `kc_pct_b` (note: dema, bbands raw moved to structural for IC analysis) |
| Volume | 5 | `ad`, `obv`, `adosc`, `bop`, `cmf` |
| Oscillators | 9 | `macd_line`, `macd_signal`, `macd_histogram`, `stoch_slowk`, `stoch_slowd`, `stochrsi_fastk`, `stochrsi_fastd`, `price_zscore`, `vwap_zscore` |
| Regression | 1 | `linearreg_slope` |
| Other | 5 | `sar`, `pivot`, `pivot_r1`, `pivot_s1`, `pivot_distance_pct` |
| Session | 11 | `vwap`, `vwap_distance_pct`, `session_high`, `session_low`, `session_position_pct`, `volume_percentile`, `volume_vs_session_avg`, `prev_session_close`, `prev_session_high`, `prev_session_low`, `gap_pct` |
| Opening Range | 5 | `night_or_high`, `night_or_low`, `day_or_high`, `day_or_low`, `or_breakout` |
| Time/Context | 9 | `bar_of_day`, `bars_remaining`, `total_bars_today`, `has_night_session`, `bar_of_session`, `bars_remaining_in_session`, `session_bars_total`, `session_phase`, `volatility_state` |

---

## 2. Period Calibration by Bar Size

Indicator periods scale with bar size to maintain consistent look-back time.

| Indicator | 1-min | 5-min | 15-min | 1-hour |
|-----------|-------|-------|--------|--------|
| RSI | 120 | 28 | 10 | 3 |
| ATR | 120 | 28 | 10 | 3 |
| EMA (fast) | 60 | 12 | 4 | 2 |
| EMA (slow) | 120 | 28 | 10 | 4 |
| MACD | 60/120/45 | 12/28/9 | 4/10/3 | 2/4/2 |
| Stochastic | 60/12/12 | 14/3/3 | 5/2/2 | 3/1/1 |
| Bollinger | 120 | 28 | 10 | 4 |

---

## 3. Indicator Classification

### 3.1 Predictive Indicators (41)

Suitable for IC (Information Coefficient) analysis. Have potential linear relationships to future returns. Price-level indicators (dema, bbands raw bands) moved to structural — their IC reflects price correlation, not predictive signal.

| Category | Indicators |
|----------|------------|
| Momentum | `rsi`, `cci`, `mfi`, `willr`, `mom`, `roc` |
| Trend | `adx`, `ema`, `sma`, `tema`, `plus_di`, `minus_di`, `aroonosc` |
| Volatility | `trange`, `stddev` |
| Normalized Channels | `bbands_pct_b`, `bbands_bandwidth`, `kc_pct_b` |
| Volume | `ad`, `obv`, `adosc`, `bop`, `cmf` |
| Oscillators | `macd_line`, `macd_signal`, `macd_histogram`, `stoch_slowk`, `stoch_slowd`, `stochrsi_fastk`, `stochrsi_fastd`, `price_zscore`, `vwap_zscore` |
| Regression | `linearreg_slope` |
| Other | `sar`, `pivot_distance_pct` |
| Session (derived) | `vwap_distance_pct`, `session_position_pct`, `volume_percentile`, `volume_vs_session_avg`, `gap_pct` |
| Opening Range | `or_breakout` |

### 3.2 Structural Indicators (32)

Not suitable for IC-based factor ranking. Represent categorical states, price levels, timing controls, volatility measures, or price-level indicators whose IC reflects price correlation rather than predictive signal.

| Indicator | Nature |
|-----------|--------|
| `bar_of_day` | Integer (0 to total_bars_today-1) |
| `bars_remaining` | Integer countdown (holiday-aware) |
| `total_bars_today` | Integer (varies by bar_size and has_night) |
| `has_night_session` | Boolean (False after holidays) |
| `bar_of_session` | Integer within session (0-indexed) |
| `bars_remaining_in_session` | Integer countdown per session |
| `session_bars_total` | Integer (varies by bar_size per session) |
| `session_phase` | Categorical (bar-size-aware: see note below) |
| `volatility_state` | Categorical state (0, 1, 2) |
| `session_high`, `session_low` | Absolute price levels |
| `prev_session_close` | Previous session's closing price |
| `prev_session_high`, `prev_session_low` | Previous session's high/low levels |
| `night_or_high`, `night_or_low` | Opening range price levels |
| `day_or_high`, `day_or_low` | Opening range price levels |
| `vwap` | Absolute price level |
| `atr`, `natr` | Volatility magnitude (non-directional) |
| `highest_high`, `lowest_low` | Price channel levels |
| `kc_upper`, `kc_lower` | Keltner Channel price levels |
| `pivot`, `pivot_r1`, `pivot_s1` | Pivot point price levels |
| `dema` | Price-level MA (redundant with ema/tema for IC) |
| `bbands_upper`, `bbands_middle`, `bbands_lower` | Price-level bands (use bbands_pct_b for normalized signal) |

### 3.3 Why IC Fails for Structural Indicators

| Type | Property |
|------|----------|
| Cyclical | Repeats daily, no monotonic relationship |
| Categorical | Discrete states, not continuous |
| Price Levels | Absolute values, context-dependent |
| Volatility | Magnitude only, no directional signal |

IC values for structural indicators in market research reflect noise, not predictive signal.

---

## 4. Intraday-Specific Notes

**Session Indicators**: VWAP, session levels reset each session. Critical for intraday context.

**Opening Range**: First N bars of each session. N depends on bar size.

**Bar Count Indicators**: All bar count indicators are auto-generated and holiday-aware.
- `bar_of_day`, `bar_of_session`: Current position (0-indexed)
- `bars_remaining`, `bars_remaining_in_session`: Countdown for exit timing
- `total_bars_today`, `session_bars_total`: Totals for adaptive logic
- `has_night_session`: Holiday detection (False after Chinese holidays)
- `session_phase`, `volatility_state`: Categorical context

**Session Phase (Bar-Size-Aware)**:
The `session_phase` values depend on bar size:
- **Granular (5m, 15m)**: `night`, `morning`, `afternoon` (+ `morning_break`, `lunch_break`)
- **Aggregated (30m, 1h)**: `night_session`, `day_session`

Use `ctx.tradeable_phases` or config to get the correct phase list for your bar size.
Do NOT hardcode phase names - always use the dynamic phase list from config.

**Holiday-Aware Bar Counts (SHFE)**:
After Chinese holidays, night sessions are often cancelled.
- Normal day: `total_bars_today` includes all tradeable session bars
- No-night day: `total_bars_today` includes only day session bars
- `has_night_session` = False on post-holiday days
- Strategy should adapt: skip night-specific logic when `has_night_session == False`

**Bars per Day**: Computed from session durations / bar_size. Varies by:
- Market (SHFE has 3 sessions, Crypto is 24/7)
- Bar size (smaller bars = more bars per session)
- Holiday schedule (no night = fewer bars)

Do NOT hardcode specific bar counts - use the indicator values directly.
