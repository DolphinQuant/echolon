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

## PathsConfig

Every directory and file path echolon touches lives on `PathsConfig`. Unlike
other configs, `PathsConfig` is REQUIRED at entry points — if you don't
supply one, the library falls back to a conventional layout rooted at
`ECHOLON_PROJECT_ROOT` (defaults to cwd), which is fine for scripts but
anti-pattern for PyPI library consumption.

### Construction

**From a conventional project root** (recommended for host applications
with their own project layout):

```python
from pathlib import Path
from echolon.config.paths_config import PathsConfig

paths = PathsConfig.from_project_root(Path("/path/to/my_project"))
```

This produces the layout:
- `<root>/session/`
- `<root>/workspace/{data,current}/...`
- `<root>/output/`
- `<root>/data/`

**From platformdirs** (recommended for pip-installed end-users without a
project layout):

```python
paths = PathsConfig.from_platformdirs("echolon")
# Linux: ~/.local/share/echolon/...
# macOS: ~/Library/Application Support/echolon/...
# Windows: %APPDATA%/echolon/...
```

Requires the optional extra: `pip install echolon[platformdirs]`.

**Explicit overrides** (any field):

```python
paths = PathsConfig.from_project_root(
    root,
    market_data_dir=Path("/mnt/bigdisk/md"),
)
```

### Injection at entry points

```python
from echolon.config.markets.factory import MarketFactory
from echolon.data import run_data_pipeline, run_live_data_update

ctx = MarketFactory.build(market="SHFE", instrument="aluminum", frequency="day")
run_data_pipeline(ctx, paths=paths)
run_live_data_update(ctx, client, paths=paths)
```

### Fields

| Field | Default (conventional layout) | Description |
|---|---|---|
| `project_root` | `<root>` | Required root |
| `session_dir` | `<root>/session` | User inputs (state.json, targets) |
| `workspace_dir` | `<root>/workspace` | Runtime working directory |
| `output_dir` | `<root>/output` | Final outputs (reports, archives) |
| `raw_data_dir` | `<root>/data` | Raw source data from API/exchange |
| `market_data_dir` | `<workspace>/data/market_data` | Processed OHLCV + calendar |
| `indicators_research_dir` | `<workspace>/data/indicators/research` | Full research indicators |
| `indicators_backtest_dir` | `<workspace>/data/indicators/backtest` | Strategy-selected indicators |
| `current_dir` | `<workspace>/current` | Current iteration workspace |
| `strategy_code_dir` | `<current>/code` | Generated strategy files |
| `backtest_results_dir` | `<current>/backtest` | Backtest outputs |
| `current_analysis_dir` | `<current>/analysis` | Market metrics outputs |
| `best_params_file` | `<strategy_code>/selected_robust_trial.json` | Optimized params |
| `deploy_config_file` | `<session>/deploy_config.json` | Live deploy config |

### Migration from module-level constants

Earlier versions exposed module-level constants like `MARKET_DATA_DIR`,
`INDICATORS_BACKTEST_DIR`, `PLATFORM_AGNOSTIC_DIR` at
`echolon.config.settings`. These are all deleted. Migrate by:

```python
# OLD
from echolon.config.settings import MARKET_DATA_DIR
run_data_pipeline(ctx)
# used MARKET_DATA_DIR implicitly

# NEW
from echolon.config.paths_config import PathsConfig
paths = PathsConfig.from_project_root(project_root)
run_data_pipeline(ctx, paths=paths)
# explicitly uses paths.market_data_dir
```

`echolon.config.settings.PROJECT_ROOT` still works but emits a
`DeprecationWarning`. Use `echolon.config.settings.get_project_root()`
for non-deprecated access.
