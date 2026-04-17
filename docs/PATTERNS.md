# Patterns

Canonical strategy patterns in Echolon. Each pattern includes when to use it, the core idea, files to customize, and common errors.

## Indicator Naming Rules

1. **Column names are always lowercase.** `ATR` in JSON → `atr_14`, `atr_15`, ... in code.
2. **Use `self.get_indicator('lowercase_name')`.** Uppercase causes silent `KeyError` or `NaN`.
3. **Declare every indicator in `strategy_indicator_list.json`.** Undeclared indicators aren't pre-computed.
4. **System indicators** (`market_regime`, `session_phase`) go in `indicators_with_special_params`.

See [IND-001](errors/IND-001.md) for the casing-mismatch error.

## 1. Trend Breakout

**When to use:** Strong trending markets; instruments with persistent momentum (index futures, commodities in backwardation).

**Key idea:** Enter when price breaks above an N-day rolling high (or below an N-day rolling low for shorts). Exit on a trailing-low stop or opposite-direction break.

**Files to customize:**
- `entry.py` — compare `self.get_current_price()` to `self.get_indicator('high_20')` (or similar)
- `exit.py` — track highest-close-since-entry, exit on pullback
- `strategy_indicator_list.json` — declare `rolling_high`, `rolling_low`, `atr`

**Sketch:**

```python
def generate_signal(self) -> EntrySignalOutput:
    price = self.get_current_price()
    upper = self.get_indicator(f"rolling_high_{self.lookback}")
    regime = self.get_market_regime()
    if price > upper:
        return EntrySignalOutput(
            signal="LONG", strength=1.0, type="breakout",
            entry_reason=f"Close {price} > {self.lookback}d high {upper}",
            intent=OrderIntent.ENTRY_LONG, regime=regime,
        )
    return EntrySignalOutput(signal="HOLD", strength=0.0, type="hold",
                             entry_reason="No breakout", regime=regime)
```

**Common errors:** IND-001 (uppercase `ROLLING_HIGH`), VAL-001 (missing `regime`).

## 2. Mean Reversion

**When to use:** Range-bound markets; instruments that oscillate around a mean (pairs, yield curve spreads, some FX crosses).

**Key idea:** Enter when an oscillator crosses an oversold/overbought threshold. Exit when it reverts to neutral.

**Files to customize:**
- `entry.py` — check `self.get_indicator(f"rsi_{period}")` < 30 (oversold)
- `exit.py` — exit when RSI > 50 or a bars-held cap is reached
- `strategy_indicator_list.json` — declare `rsi` at your chosen period

**Sketch:**

```python
def generate_signal(self) -> EntrySignalOutput:
    rsi = self.get_indicator(f"rsi_{self.rsi_period}")
    regime = self.get_market_regime()
    if rsi < self.oversold_threshold:
        return EntrySignalOutput(
            signal="LONG", strength=1.0, type="oversold",
            entry_reason=f"RSI={rsi} below {self.oversold_threshold}",
            intent=OrderIntent.ENTRY_LONG, regime=regime,
        )
    return EntrySignalOutput(signal="HOLD", strength=0.0, type="hold",
                             entry_reason="Not oversold", regime=regime)
```

**Common errors:** PRM-001 (missing `printlog` in `entry_params`), VAL-002 (using `BUY` instead of `LONG`).

## 3. Regime-Switching

**When to use:** Strategies that must behave differently based on market condition — e.g., momentum in trending regimes, mean reversion in ranging.

**Key idea:** Branch the entry/exit logic on `self.get_market_regime()`. The system regime indicator classifies bars as `trending_up`, `trending_down`, `ranging`, or `volatile`.

**Files to customize:**
- `entry.py` — outer `if regime == "trending_up"` branches
- `strategy_indicator_list.json` — add `market_regime` to `indicators_with_special_params`
- `strategy_params.py` — define per-regime thresholds (e.g., `trend_threshold`, `range_threshold`)

**Sketch:**

```python
def generate_signal(self) -> EntrySignalOutput:
    regime = self.get_market_regime()
    price = self.get_current_price()
    if regime == "trending_up":
        upper = self.get_indicator(f"rolling_high_{self.trend_lookback}")
        if price > upper:
            return EntrySignalOutput(
                signal="LONG", strength=1.0, type="trend_break",
                entry_reason="Trending regime breakout",
                intent=OrderIntent.ENTRY_LONG, regime=regime,
            )
    elif regime == "ranging":
        rsi = self.get_indicator(f"rsi_{self.rsi_period}")
        if rsi < 30:
            return EntrySignalOutput(
                signal="LONG", strength=1.0, type="range_revert",
                entry_reason="Range oversold",
                intent=OrderIntent.ENTRY_LONG, regime=regime,
            )
    return EntrySignalOutput(signal="HOLD", strength=0.0, type="hold",
                             entry_reason=f"No signal in {regime}", regime=regime)
```

**Common errors:** IND-002 (forgetting to declare `market_regime` in JSON), VAL-001 (missing `regime` in HOLD branch).

## 4. Multi-Timeframe

**When to use:** Intraday execution informed by a higher-timeframe bias (e.g., take long signals only when daily EMA is rising).

**Key idea:** Pre-compute the higher-timeframe indicator at daily frequency, then expose its last value to each intraday bar via the indicator pipeline. The strategy code sees a single indicator column; resampling is done upstream.

**Files to customize:**
- `strategy_indicator_list.json` — add a daily-resampled indicator like `ema_daily_50`
- `entry.py` — gate signals on the daily indicator before checking intraday triggers

**Sketch:**

```python
def generate_signal(self) -> EntrySignalOutput:
    daily_ema = self.get_indicator("ema_daily_50")
    intraday_ema = self.get_indicator(f"ema_{self.fast_period}")
    price = self.get_current_price()
    regime = self.get_market_regime()
    long_bias = price > daily_ema
    if long_bias and price > intraday_ema:
        return EntrySignalOutput(
            signal="LONG", strength=1.0, type="mtf_pullback",
            entry_reason="Above daily EMA and intraday EMA",
            intent=OrderIntent.ENTRY_LONG, regime=regime,
        )
    return EntrySignalOutput(signal="HOLD", strength=0.0, type="hold",
                             entry_reason="No MTF alignment", regime=regime)
```

**Common errors:** IND-002 (daily indicator not declared), DAT-001 (daily data file missing).

## 5. ML Signal

**When to use:** You have a trained model (scikit-learn, XGBoost, small PyTorch) that outputs a directional score from a fixed feature vector.

**Key idea:** Load the pickled model once in `__init__`. In `generate_signal()`, build the feature vector from `self.get_indicator(...)` calls, call `model.predict_proba`, and threshold the output.

**Files to customize:**
- `entry.py` — `__init__` loads the model; `generate_signal` builds features and predicts
- `strategy_indicator_list.json` — declare every feature the model expects
- `strategy_params.py` — expose the probability threshold as a tunable parameter

**Sketch:**

```python
import joblib
import numpy as np
from pathlib import Path

class entry_rule(BaseComponent):
    def __init__(self, trading_engine, **params):
        super().__init__(trading_engine, **params)
        self.model = joblib.load(Path(self.params["model_path"]))
        self.prob_threshold = self.params["prob_threshold"]

    def generate_signal(self) -> EntrySignalOutput:
        regime = self.get_market_regime()
        features = np.array([[
            self.get_indicator("rsi_14"),
            self.get_indicator("atr_14"),
            self.get_indicator("ema_20"),
        ]])
        prob_long = float(self.model.predict_proba(features)[0, 1])
        if prob_long > self.prob_threshold:
            return EntrySignalOutput(
                signal="LONG", strength=prob_long, type="ml_long",
                entry_reason=f"p(long)={prob_long:.3f}",
                intent=OrderIntent.ENTRY_LONG, regime=regime,
            )
        return EntrySignalOutput(signal="HOLD", strength=0.0, type="hold",
                                 entry_reason="Below threshold", regime=regime)
```

**Common errors:** DAT-001 (model file missing), IND-002 (feature indicator not declared), PRM-002 (`model_path` missing from `entry_params`).
