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
