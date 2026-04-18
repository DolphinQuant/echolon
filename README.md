# Echolon

See what others can't.

> Private development repo. Full README with launch content coming before public release.

## Configuration

Echolon exposes typed configuration via Pydantic models. Each component
receives only the configs it needs.

### Quick start

```python
import echolon

ctx, bt, opt = echolon.quick_start(
    market="shfe",
    instrument="cu",
    start_date="2020-01-01",
    end_date="2025-12-31",
)

# Override defaults as needed
opt.n_trials = 500
```

### Full API

- `TradingContext` — market, instrument, frequency
- `BacktestConfig` — dates, paths, thresholds
- `OptunaConfig` — trials, target, parallelism
- `WFAConfig` — walk-forward windows
- `IndicatorConfig` — indicator period caps (defaults usually fine)

### Environment variables

- `ECHOLON_WORKSPACE_DIR` (default `./workspace`) — results, strategy code
- `ECHOLON_DATA_DIR` (default `./data`) — market data, indicator cache
- `ECHOLON_LOG_LEVEL` (default `INFO`)
- `ECHOLON_N_JOBS_DEFAULT` (default `-1`) — Optuna parallelism

## AI-Native Documentation

Echolon is designed for both humans and AI coding agents. See:

- [`llms.txt`](./llms.txt) — AI agent entry point with instructions
- [`docs/`](./docs/) — structured documentation
- [`examples/`](./examples/) — working strategies to learn from

## CLI

```bash
pip install echolon
echolon init-strategy my_first --template minimal
echolon validate my_first/
echolon run my_first/ --instrument cu --start 2020-01-01 --end 2023-12-31
```

## Live Deployment

### Strategy directory contract

Organize your strategy as a directory with these files:

```
my_strategy/
├── strategy_code.py             # BaseStrategy subclass + components (REQUIRED)
├── strategy_params.py           # optuna_search_space (optional for deploy)
├── selected_robust_trial.json   # chosen trial params (REQUIRED)
├── strategy_indicator_list.json # indicator spec (REQUIRED)
└── regime_params.json           # per-regime params (REQUIRED if regime-aware)
```

### Single-instrument deployment

```bash
echolon deploy single --config deploy_config.json
```

### Portfolio deployment

```bash
echolon deploy portfolio --config portfolio_deploy_config.json
echolon deploy portfolio --config portfolio_deploy_config.json --validate-only  # dry-run
echolon deploy portfolio-cycle --config portfolio_deploy_config.json            # one cycle only
```

Paths in `portfolio_deploy_config.json` (`strategy_code_dir`, `trial_params_path`) are resolved relative to the config file's directory.

### Pre-deploy backtest

```bash
echolon backtest portfolio --config portfolio_deploy_config.json \
    --start 2020-01-01 --end 2024-12-31 \
    --output-dir ./workspace/portfolio_backtest
```
