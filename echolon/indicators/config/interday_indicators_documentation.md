# Interday Indicators Documentation

## 1. Overview

This document describes the **49 technical indicators** used for interday (daily bars) market analysis and strategy development. The pool is designed to maximize independent signal coverage while letting the market_metrics clustering gate (max 2 per cluster in top-factor lists) handle redundancy automatically. Non-signal indicators, price-level indicators (raw MAs, price channels, fitted regression values), and redundant MA variants are excluded:

- Math operators and trigonometric functions (20 removed)
- Exotic candlestick patterns (60 removed)
- Complex Hilbert transforms (8 removed)
- Index-returning indicators (4 removed)
- Math aggregation operators (5 removed)
- Benchmark-dependent indicators (2 removed)
- Variable-period dependent (1 removed)
- Identical ROC variants (3 removed)
- Redundant MACD variants (6 removed)
- SR zone indicators (4 removed)
- Redundant/unused MAs (8 removed): MA, WMA, DEMA, TRIMA, MIDPOINT, T3, MAMA, FAMA
- Price-level indicators (5 removed): HIGHEST_HIGH, LOWEST_LOW, BBANDS_UPPER/MIDDLE/LOWER
- Price-level regression (3 removed): LINEARREG, LINEARREG_INTERCEPT, TSF
- Redundant SAR (1 removed): SAREXT

## 2. Data Context

- **Frequency**: Daily (interday). Each row represents a single trading day.
- **Data Source**: Continuous rolling main futures contract (e.g., SHFE Aluminum)
- **Indicator Count**: 49 indicators

---

## 3. Core Market Data (Not Indicators)

Core price and volume information available in the dataset:

| Column | Description |
|--------|-------------|
| `open` | Opening price |
| `high` | Highest price |
| `low` | Lowest price |
| `close` | Closing price |
| `volume` | Trading volume (number of contracts) |
| `date` | Trading date |
| `contract` | Futures contract identifier (e.g., `al2401`) |

---

## 4. Indicators by Category

### 4.1. Market Regime (1 indicator)

Classification of current market state for regime-adaptive strategies.

| Indicator | Description |
|-----------|-------------|
| `market_regime` | Market state classification based on trend and volatility. Values: `trending_up`, `trending_down`, `ranging`, `volatile`. Uses ADX for trend strength and SMA for direction. |

**Regime Definitions:**
- `trending_up`: Price above SMA + strong trend (ADX > 25)
- `trending_down`: Price below SMA + strong trend (ADX > 25)
- `ranging`: Weak trend (ADX <= 25) + moderate volatility
- `volatile`: Very high volatility (ADX > 40)

---

### 4.2. Momentum Indicators (7 indicators)

Measure velocity and strength of price changes.

| Indicator | Description | Typical Range |
|-----------|-------------|---------------|
| `rsi` | Relative Strength Index. Overbought/oversold oscillator. | 0-100 (>70 overbought, <30 oversold) |
| `cci` | Commodity Channel Index. Deviation from average price. | Unbounded, typically -200 to +200 |
| `cmo` | Chande Momentum Oscillator. Normalized momentum with different formula from RSI. | -100 to +100 |
| `mfi` | Money Flow Index. Volume-weighted RSI. | 0-100 |
| `willr` | Williams %R. Momentum showing overbought/oversold. | -100 to 0 |
| `mom` | Momentum. Absolute price change over N periods. | Unbounded |
| `roc` | Rate of Change. Percentage price change: ((price/prevPrice)-1)*100 | Unbounded |

---

### 4.3. Trend Indicators (10 indicators)

Identify direction and strength of market trends.

**Directional Movement System:**

| Indicator | Description | Typical Range |
|-----------|-------------|---------------|
| `adx` | Average Directional Index. Trend strength (not direction). | 0-100 (>25 = strong trend) |
| `adxr` | ADX Rating. Smoothed version of ADX, measures trend persistence. | 0-100 |
| `dx` | Directional Movement Index. Raw directional movement. | 0-100 |
| `plus_di` | Plus Directional Indicator. Upward movement strength. | 0-100 |
| `minus_di` | Minus Directional Indicator. Downward movement strength. | 0-100 |
| `plus_dm` | Plus Directional Movement. Raw upward movement (before smoothing to DI). | >= 0 |
| `minus_dm` | Minus Directional Movement. Raw downward movement (before smoothing to DI). | >= 0 |

**Aroon System:**

| Indicator | Description | Typical Range |
|-----------|-------------|---------------|
| `aroon_up` | Aroon Up. Bars since N-period high (recency of high). | 0-100 |
| `aroon_down` | Aroon Down. Bars since N-period low (recency of low). | 0-100 |
| `aroonosc` | Aroon Oscillator. aroon_up - aroon_down. | -100 to +100 |

---

### 4.4. Moving Averages (4 indicators)

Core smoothed price series for trend identification and signal generation. Redundant MA variants (MA, WMA, DEMA, TRIMA, MIDPOINT, T3, MAMA, FAMA) removed — clustering gate handles within-category redundancy.

| Indicator | Description | Responsiveness |
|-----------|-------------|----------------|
| `sma` | Simple Moving Average. Equal-weighted average of N closes. | Slow |
| `ema` | Exponential Moving Average. More weight to recent prices. | Medium |
| `tema` | Triple EMA. Even faster-responding, proven DRS 88.2 pathway. | Very Fast |
| `kama` | Kaufman Adaptive Moving Average. Adapts smoothing to market noise — flat in ranges, responsive in trends. | Adaptive |

**Note**: Price-level MAs produce absolute thresholds that become stale as price regimes shift. Prefer normalized alternatives (bbands_pct_b, trix) when possible.

---

### 4.5. Volatility Indicators (5 indicators)

Measure magnitude and nature of price fluctuations.

| Indicator | Description | Notes |
|-----------|-------------|-------|
| `atr` | Average True Range. Average of true ranges over N periods. | Absolute value in price units |
| `natr` | Normalized ATR. ATR as percentage of close price. | Percentage (0-100+) |
| `trange` | True Range. Single-period volatility measure. | Absolute value |
| `stddev` | Standard Deviation. Statistical dispersion of prices. | Absolute value |
| `var` | Variance. Square of standard deviation. | Absolute value |

---

### 4.6. Bollinger Band Signals (2 indicators)

Normalized Bollinger Band indicators for mean-reversion and squeeze detection. Raw price-level bands (bbands_upper/middle/lower, highest_high, lowest_low) removed — their absolute values produce stale thresholds.

| Indicator | Description |
|-----------|-------------|
| `bbands_pct_b` | Bollinger %B. Normalized position within bands (0 = lower, 0.5 = middle, 1 = upper). Bounded oscillator. |
| `bbands_bandwidth` | Bollinger Bandwidth. Band width as % of middle band. Low = squeeze (potential breakout), High = expansion. |

---

### 4.7. Volume Indicators (3 indicators)

Incorporate trading volume for confirmation signals.

| Indicator | Description |
|-----------|-------------|
| `ad` | Accumulation/Distribution Line. Cumulative volume-weighted price momentum. |
| `obv` | On Balance Volume. Cumulative volume based on price direction. |
| `adosc` | Chaikin A/D Oscillator. Momentum (rate of change) of the AD line. Fast EMA(AD) - Slow EMA(AD). |

---

### 4.8. Oscillators (13 indicators)

Bounded indicators for identifying overbought/oversold conditions and momentum.

**MACD Family:**

| Indicator | Description |
|-----------|-------------|
| `macd_line` | MACD Line. Fast EMA - Slow EMA (default: 12/26). |
| `macd_signal` | MACD Signal Line. EMA of MACD Line (default period: 9). |
| `macd_histogram` | MACD Histogram. macd_line - macd_signal. |

**Price Oscillators:**

| Indicator | Description |
|-----------|-------------|
| `apo` | Absolute Price Oscillator. Similar to MACD with customizable periods and MA type. |
| `ppo` | Percentage Price Oscillator. Normalized version of APO (percentage-based). |
| `trix` | Triple-smoothed EMA Rate of Change. Ultra-smooth momentum, filters noise for major trend changes. |
| `ultosc` | Ultimate Oscillator. Multi-timeframe oscillator combining 7/14/28 period buying pressure. |

**Stochastic Family:**

| Indicator | Description | Range |
|-----------|-------------|-------|
| `stoch_slowk` | Stochastic Slow %K. Position of close within high-low range. | 0-100 |
| `stoch_slowd` | Stochastic Slow %D. Moving average of Slow %K. | 0-100 |
| `stochf_fastk` | Stochastic Fast %K. Unsmoothed position of close within range. | 0-100 |
| `stochf_fastd` | Stochastic Fast %D. Moving average of Fast %K. | 0-100 |
| `stochrsi_fastk` | StochRSI Fast %K. Stochastic applied to RSI. | 0-100 |
| `stochrsi_fastd` | StochRSI Fast %D. Moving average of StochRSI %K. | 0-100 |

---

### 4.9. Regression Indicators (2 indicators)

Linear regression-based normalized trend signals. Price-level regression outputs (linearreg, linearreg_intercept, tsf) removed — fitted price values produce stale absolute thresholds.

| Indicator | Description |
|-----------|-------------|
| `linearreg_slope` | Linear Regression Slope. Rate of change of best-fit line. Positive = uptrend, negative = downtrend. |
| `linearreg_angle` | Linear Regression Angle. Angular transform of slope (degrees). |

---

### 4.10. Other Indicators (2 indicators)

| Indicator | Description |
|-----------|-------------|
| `sar` | Parabolic Stop and Reverse. Trend-following stop-loss indicator. Provides trailing stop levels. |
| `bop` | Balance of Power. (close - open) / (high - low). Measures intra-bar buying/selling pressure. |

---

## 5. Indicator Usage Notes

### Naming Convention
Indicators with lookback periods are suffixed with `_N` where N is the period length:
- `rsi_14` = RSI with 14-period lookback
- `sma_50` = 50-day Simple Moving Average
- `kama_30` = 30-period Kaufman Adaptive MA

### Default Parameters
| Indicator | Default Period(s) |
|-----------|-------------------|
| RSI, ADX, ATR, CCI, CMO | 14 |
| Moving Averages (EMA, SMA, etc.) | 20-50 (varies) |
| KAMA | 30 |
| TRIX | 30 |
| MACD | 12, 26, 9 (fast, slow, signal) |
| Stochastic | 5, 3, 3 (fastk, slowk, slowd) |
| Bollinger Bands | 20, 2 (period, std dev) |
| ULTOSC | 7, 14, 28 (short, medium, long) |

### Multi-Output Indicators
Some indicators return multiple values split into separate columns:
- MACD -> `macd_line`, `macd_signal`, `macd_histogram`
- Stochastic -> `stoch_slowk`, `stoch_slowd`
- Fast Stochastic -> `stochf_fastk`, `stochf_fastd`
- Bollinger -> `bbands_pct_b`, `bbands_bandwidth`

---

## 6. Summary Table

| Category | Count | Indicators |
|----------|-------|------------|
| Regime | 1 | market_regime |
| Momentum | 7 | rsi, cci, cmo, mfi, willr, mom, roc |
| Trend | 10 | adx, adxr, dx, plus_di, minus_di, plus_dm, minus_dm, aroon_up, aroon_down, aroonosc |
| Moving Averages | 4 | sma, ema, tema, kama |
| Volatility | 5 | atr, natr, trange, stddev, var |
| Bollinger Signals | 2 | bbands_pct_b, bbands_bandwidth |
| Volume | 3 | ad, obv, adosc |
| Oscillators | 13 | macd_line, macd_signal, macd_histogram, apo, ppo, trix, ultosc, stoch_slowk, stoch_slowd, stochf_fastk, stochf_fastd, stochrsi_fastk, stochrsi_fastd |
| Regression | 2 | linearreg_slope, linearreg_angle |
| Other | 2 | sar, bop |
| **Total** | **49** | |
