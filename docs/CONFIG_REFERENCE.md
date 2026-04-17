# Configuration Reference

Echolon uses Pydantic v2 models for all configuration. Each config class is a typed object — IDEs and LLMs can introspect it.

## BacktestConfig

See [API_REFERENCE.md#backtestconfig](API_REFERENCE.md#backtestconfig).

Common mistakes:
- `end_date` before `start_date` → CFG-001
- Missing directory path → CFG-002

## OptunaConfig

See [API_REFERENCE.md#optunaconfig](API_REFERENCE.md#optunaconfig).

The `target` field accepts:
- `"sharpe_ratio"` — maximize risk-adjusted return (default)
- `"total_return"` — maximize absolute return
- `"annual_return"` — maximize annualized return
- `"drawdown"` — minimize max drawdown
- `"multi_objective"` — Pareto frontier over Sharpe + drawdown

## TradingContext

Runtime context: market, instrument, frequency, bar size.

```python
from echolon import TradingContext

ctx = TradingContext.from_market(
    market="shfe",
    instrument="cu",
    frequency="interday",
    bar_size="1d",
)
```

## Environment Variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `ECHOLON_WORKSPACE_DIR` | `./workspace` | Workspace root |
| `ECHOLON_DATA_DIR` | `./data` | Market data + indicators |
| `ECHOLON_LOG_LEVEL` | `INFO` | Logging verbosity |
| `ECHOLON_N_JOBS_DEFAULT` | `-1` | Default Optuna parallelism |

Set via shell export, `.env` file, or Docker env config.

## quick_start()

For common cases, use the convenience helper:

```python
from echolon import quick_start

ctx, bt, opt = quick_start(
    market="shfe",
    instrument="cu",
    start_date="2020-01-01",
    end_date="2023-12-31",
)
# Override anything
opt.n_trials = 500
bt.max_drawdown_pct = 20.0
```

`quick_start` uses env vars for paths with fallbacks to `./workspace` and `./data`.
