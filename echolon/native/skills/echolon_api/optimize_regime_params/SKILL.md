---
name: optimize_regime_params
description: Convenience wrapper around InterdayRegimeOptimizer — runs an Optuna hyperparameter search for the interday market_regime classifier and returns the winning regime_params dict ready to pass into run_indicator_calculation.
type: skill
category: echolon_api
primary_scope: universal
echolon_version: unpinned
origin_module: echolon_audit_phase0
---

# echolon.indicators.optimize_regime_params

## Purpose

`optimize_regime_params(ctx, data_dir=None, n_trials=400, config=None, backtest_start_year=None, indicator_config=None, paths=None)` is the convenience wrapper around `InterdayRegimeOptimizer.optimize()`. It takes a `TradingContext`, resolves the contract data directory (`{paths.market_data_dir}/{market}/{instrument}/sort_by_contract`), constructs an `InterdayRegimeOptimizer` (or takes one you provide via `config`), runs the Optuna study, and returns just the winning parameter dict — shape-compatible with the `regime_params=` kwarg of `run_indicator_calculation`. It only works on interday ctx (daily bars); intraday regime handling uses session-phase + volatility-state instead and this function rejects non-interday contexts with a `ValueError`.

## Interface

```python
from echolon.config.markets.factory import MarketFactory
from echolon.indicators import optimize_regime_params
from echolon.indicators.optimization import InterdayRegimeOptimizer  # for custom config
from echolon.config.paths_config import PathsConfig

ctx = MarketFactory.from_session()   # must be interday

# 1. Simplest: defaults everything, 400 trials.
regime_params = optimize_regime_params(ctx)

# 2. Tuned call count + explicit data directory.
regime_params = optimize_regime_params(
    ctx,
    n_trials=200,
    data_dir="/path/to/cu/sort_by_contract",
    backtest_start_year=2018,
)

# 3. Custom optimizer config + paths injection.
from echolon.indicators.optimization.interday_regime_optimizer import (
    RegimeOptimizerConfig,
)
regime_params = optimize_regime_params(
    ctx,
    config=RegimeOptimizerConfig(n_trials=300),
    paths=PathsConfig.from_env(),
)

# 4. Typical downstream use — plug into the indicator pipeline.
from echolon.indicators.run import run_indicator_calculation
df = run_indicator_calculation(
    ctx,
    output_dir="/path/to/indicators/cu",
    indicator_list={"market_regime": {}, "rsi": {"timeperiod": [14]}},
    regime_params=regime_params,
    start_date="2018-01-01",
    end_date="2024-12-31",
)
```

## When to use

- Immediately before `run_indicator_calculation` whenever the indicator list contains `market_regime` on an interday context. The regime classifier has its own hyperparameters (bounds, weights), and this step picks robust values from historical contract data under `{paths.market_data_dir}/{market}/{instrument}/sort_by_contract/`.
- When you want the convenience entry point over constructing `InterdayRegimeOptimizer` directly — the docstring explicitly calls this out: "The caller should prefer this function over constructing InterdayRegimeOptimizer directly so that future API changes are absorbed here."
- Do *not* call this on an intraday ctx. The function checks `ctx.is_interday` and raises `ValueError` — intraday strategies rely on `session_phase` + `volatility_state` instead of regime classification.
- Do *not* hardcode `data_dir` unless you have a good reason. Passing `paths=PathsConfig.from_env()` (or leaving `paths=None` and letting the function resolve it) keeps the layout aligned with the rest of the pipeline.

## Parameters / Returns

| Method | Args | Returns | Purpose |
|---|---|---|---|
| `optimize_regime_params(ctx, data_dir=None, n_trials=400, config=None, backtest_start_year=None, indicator_config=None, paths=None)` | see above | `Dict` | Regime parameter dict — shape matches `run_indicator_calculation(... regime_params=...)`. |

Resolution rules:
- **`data_dir`**: explicit > derived from `paths` > `PathsConfig.from_env()`. Derived form: `{paths.market_data_dir}/{ctx.market_code}/{ctx.instrument_name}/sort_by_contract`. When both `data_dir` and `paths` are supplied, `data_dir` wins.
- **`config`**: if `None`, a `RegimeOptimizerConfig(n_trials=n_trials)` is built automatically.
- **`indicator_config`**: optional `IndicatorConfig` override for indicator period caps used inside the regime classifier.
- **`backtest_start_year`**: filters contracts — pass `2018` to skip older data.

Under the hood: `InterdayRegimeOptimizer(data_dir, config, futures=ctx.instrument_name, market=ctx.market_code, backtest_start_year, indicator_config).optimize(n_trials=n_trials)` returns `(best_params, study)`; this wrapper discards the study and returns only `best_params`.

## Common errors

- **`ValueError: optimize_regime_params requires an interday ctx; got frequency='intraday'`** — the ctx is intraday. Regime optimization is daily-bar-only. For intraday strategies use `session_phase` + `volatility_state` (already calculated by `run_indicator_calculation` when `indicator_list` includes those indicators).
- **`FileNotFoundError` on `sort_by_contract/*.csv`** — the data pipeline never produced per-contract files. Run `run_data_pipeline(ctx)` first so `ContractSplitter` writes the `sort_by_contract/` subdirectory. No Echolon code.
- **Downstream Optuna failures inside `InterdayRegimeOptimizer.optimize`** — these surface as raw Optuna / strategy errors. This wrapper does not catch them. Inspect the inner optimizer's logs.

## See also

- `run_indicator_calculation` skill — the immediate downstream consumer of the returned `regime_params` dict.
- `run_data_pipeline` skill — must run first to produce the `sort_by_contract/` CSVs read here.
- `trading_context` skill — `ctx.is_interday`, `ctx.market_code`, `ctx.instrument_name` are all used.
- `market_factory` skill — the source of `ctx`.
- echolon docs: `echolon/indicators/optimization/interday_regime_optimizer.py` (`InterdayRegimeOptimizer`, `RegimeOptimizerConfig`, `IndicatorConfig`).
