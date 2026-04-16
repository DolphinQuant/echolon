# Interday Indicator Classification and Naming Convention

**Version**: 3.0
**Last Updated**: 2026-02-13
**Frequency**: Interday (Daily bars)
**Indicator Count**: 49 indicators

---

## Purpose

This document defines the **three-tier indicator system** for interday (daily bar) trading strategies. It specifies:

1. **Classification**: Which indicators belong to which tier
2. **Naming Conventions**: How indicator names are constructed at runtime
3. **Optimization Capabilities**: Which indicators can be optimized via Optuna
4. **Default Parameters**: What default values are used for special parameter indicators

**Authoritative Source**: `modules/indicators/config/interday_analysis_indicators.json`

**Design Philosophy**: Maximize the pool of plausible trading signals. Redundancy within the pool is handled by the market_metrics clustering gate (max 2 per cluster in top-factor lists). The IC analysis determines the best representative per regime from the full candidate set.

---

## Three-Tier Indicator System

### Tier 1: Indicators with Lookback Periods (OPTIMIZABLE)

**Naming Convention**: `{name}_{period}` (lowercase) at runtime
**Optimization**: YES - single integer period parameter can be optimized

#### Available Indicators (26 total)

**Volatility Indicators (2)**:
- `ATR` - Average True Range
- `NATR` - Normalized Average True Range

**Momentum Indicators (17)**:
- `ADX` - Average Directional Index
- `ADXR` - ADX Rating
- `AROON_DOWN` - Aroon Down
- `AROON_UP` - Aroon Up
- `AROONOSC` - Aroon Oscillator
- `CCI` - Commodity Channel Index
- `CMO` - Chande Momentum Oscillator
- `DX` - Directional Movement Index
- `MFI` - Money Flow Index
- `MINUS_DI` - Minus Directional Indicator
- `MINUS_DM` - Minus Directional Movement
- `MOM` - Momentum
- `PLUS_DI` - Plus Directional Indicator
- `PLUS_DM` - Plus Directional Movement
- `ROC` - Rate of Change
- `RSI` - Relative Strength Index
- `WILLR` - Williams %R

**Moving Averages (5)**:
- `EMA` - Exponential Moving Average
- `KAMA` - Kaufman Adaptive Moving Average
- `SMA` - Simple Moving Average
- `TEMA` - Triple Exponential Moving Average
- `TRIX` - Triple Exponential EMA Rate of Change

**Statistics & Regression (2)**:
- `LINEARREG_ANGLE` - Linear Regression Angle
- `LINEARREG_SLOPE` - Linear Regression Slope

#### Naming Examples

**In strategy output**:
```json
{
  "required_indicators": ["ADX", "ATR", "RSI", "EMA"],
  "optimizable_calculation_parameters": {
    "adx_period": {"type": "int", "min": 10, "max": 20, "default": 14},
    "atr_period": {"type": "int", "min": 10, "max": 21, "default": 14},
    "rsi_period": {"type": "int", "min": 10, "max": 20, "default": 14},
    "ema_period": {"type": "int", "min": 10, "max": 50, "default": 20}
  }
}
```

**Runtime indicator names**:
- `adx_14`, `atr_20`, `rsi_14`, `ema_20` (constructed with period suffix)

---

### Tier 2: Indicators with Special Parameters (NON-OPTIMIZABLE)

**Naming Convention**: `{name}` (lowercase, NO parameter suffix!)
**Optimization**: NO - use built-in defaults

#### Why Non-Optimizable?

These indicators have **2+ non-period parameters** creating exponential search spaces. Use industry-standard defaults for baseline strategies.

#### Available Indicators (19 total)

**MACD Family (3)**:
- `MACD_LINE` - MACD line (fast EMA - slow EMA)
- `MACD_SIGNAL` - MACD signal line
- `MACD_HISTOGRAM` - MACD histogram

**Default Parameters**: `fastperiod=12, slowperiod=26, signalperiod=9`

**Price Oscillators (2)**:
- `APO` - Absolute Price Oscillator (fast EMA - slow EMA, customizable)
- `PPO` - Percentage Price Oscillator (normalized APO)

**Default Parameters**: `fastperiod=12, slowperiod=26, matype=0`

**Stochastic Family (6)**:
- `STOCH_SLOWK` - Stochastic Slow %K
- `STOCH_SLOWD` - Stochastic Slow %D
- `STOCHF_FASTK` - Stochastic Fast %K (unsmoothed)
- `STOCHF_FASTD` - Stochastic Fast %D
- `STOCHRSI_FASTK` - Stochastic RSI Fast %K
- `STOCHRSI_FASTD` - Stochastic RSI Fast %D

**Default Parameters**: `stoch: fastk_period=5, slowk_period=3, slowd_period=3`

**Bollinger Bands (2)**:
- `BBANDS_PCT_B` - Bollinger %B (normalized position within bands, 0-1 scale)
- `BBANDS_BANDWIDTH` - Bollinger Bandwidth (band width as % of middle, squeeze detection)

**Default Parameters**: `timeperiod=20, nbdevup=2, nbdevdn=2`

**Multi-Timeframe Oscillators (1)**:
- `ULTOSC` - Ultimate Oscillator (7/14/28 period)

**Default Parameters**: `timeperiod1=7, timeperiod2=14, timeperiod3=28`

**Statistics (2)**:
- `STDDEV` - Standard Deviation
- `VAR` - Variance

**Default Parameters**: `timeperiod=5, nbdev=1`

**Volume (1)**:
- `ADOSC` - Chaikin A/D Oscillator (AD momentum)

**Default Parameters**: `fastperiod=3, slowperiod=10`

**Other (1)**:
- `SAR` - Parabolic SAR

**Default Parameters**: `SAR: acceleration=0.02, maximum=0.2`

**Regime (1)**:
- `MARKET_REGIME` - Market regime classification (trending_up, trending_down, ranging)

#### Naming Examples

**Runtime indicator names**:
- `macd_line` (NOT `macd_line_12_26_9`)
- `bbands_pct_b` (NOT `bbands_pct_b_20_2`)
- `market_regime`

---

### Tier 3: Indicators without Lookback (NON-OPTIMIZABLE)

**Naming Convention**: `{name}` (lowercase)
**Optimization**: N/A - no parameters

#### Available Indicators (4 total)

**Volume Indicators (2)**:
- `AD` - Chaikin A/D Line
- `OBV` - On Balance Volume

**Volatility (1)**:
- `TRANGE` - True Range

**Price Action (1)**:
- `BOP` - Balance of Power ((close - open) / (high - low))

#### Naming Examples

**Runtime indicator names**: `ad`, `obv`, `trange`, `bop`

---

## Interday-Specific Context

### Primary Filter: Market Regime

For interday strategies, `market_regime` is the PRIMARY filter controlling WHEN to trade:

```python
IF market_regime == 'trending_up'
AND [indicator] [comparison] [threshold]
THEN ENTER LONG
```

**Regime Values**:
- `trending_up`: Bullish trend - trend following strategies
- `trending_down`: Bearish trend - short strategies or avoid
- `ranging`: Sideways market - mean reversion strategies

### Typical Indicator Periods (Daily Bars)

| Indicator | Common Range | Default |
|-----------|--------------|---------|
| RSI | 10-20 | 14 |
| ADX | 10-20 | 14 |
| ATR | 10-21 | 14 |
| EMA | 10-50 | 20 |
| SMA | 20-200 | 50 |
| KAMA | 10-30 | 30 |
| TRIX | 15-30 | 30 |

---

## Critical Parameter Distinction

### Calculation Parameters vs Usage Parameters

**Calculation Parameters** (Technical):
- Configure HOW an indicator is calculated
- Only for Tier 1 indicators
- Example: `adx_period = 14` -> Use 14-day lookback

**Usage Parameters** (Business Logic):
- Define trading decision thresholds
- For all tiers
- Example: `adx_threshold = 25` -> Enter when ADX > 25

---

## Quick Reference Table

| Tier | Example | Runtime Name | Optimize? |
|------|---------|--------------|-----------|
| 1 (with_lookback) | ADX | `adx_14` | YES |
| 1 (with_lookback) | KAMA | `kama_30` | YES |
| 1 (with_lookback) | TRIX | `trix_30` | YES |
| 2 (special_params) | MACD_LINE | `macd_line` | NO |
| 2 (special_params) | BBANDS_PCT_B | `bbands_pct_b` | NO |
| 2 (special_params) | MARKET_REGIME | `market_regime` | NO |
| 3 (without_lookback) | OBV | `obv` | N/A |
| 3 (without_lookback) | BOP | `bop` | N/A |

---

## All 49 Interday Indicators

```
atr, adx, adxr, aroon_down, aroon_up, aroonosc, cci, cmo, dx, mfi,
minus_di, minus_dm, mom, plus_di, plus_dm, roc, rsi, willr,
ema, kama, sma, tema, trix,
linearreg_angle, linearreg_slope,
natr, trange,
ad, adosc, obv,
apo, bop, macd_line, macd_signal, macd_histogram, ppo,
stoch_slowk, stoch_slowd, stochf_fastk, stochf_fastd,
stochrsi_fastk, stochrsi_fastd, ultosc,
bbands_pct_b, bbands_bandwidth,
sar, stddev, var, market_regime
```
