# API Reference

All public Echolon classes and their signatures.

## BacktestConfig

**Module:** `echolon.config.backtest_config`

**Purpose:** Configuration for a single backtest run — dates, paths, thresholds.

**Signature:**

```python
BacktestConfig(
    start_date: str,            # "YYYY-MM-DD"
    end_date: str,              # "YYYY-MM-DD"
    strategy_dir: Path,
    market_data_dir: Path,
    indicator_dir: Path,
    results_dir: Path,
    max_drawdown_pct: float = 15.0,
    is_end_date: Optional[str] = None,
    oos_start_date: Optional[str] = None,
    market_research_end_date: Optional[str] = None,
)
```

**Example:**

```python
from echolon import BacktestConfig
from pathlib import Path

cfg = BacktestConfig(
    start_date="2020-01-01",
    end_date="2023-12-31",
    strategy_dir=Path("./my_strategy"),
    market_data_dir=Path("./data/market"),
    indicator_dir=Path("./data/indicators"),
    results_dir=Path("./results"),
)
```

**Common errors:** CFG-001, CFG-002.

## OptunaConfig

**Module:** `echolon.config.optuna_config`

**Purpose:** Optuna hyperparameter optimization settings.

**Signature:**

```python
OptunaConfig(
    n_trials: int = 100,
    n_jobs: int = -1,
    timeout: Optional[int] = None,
    target: Literal["sharpe_ratio", "total_return", "annual_return", "drawdown", "multi_objective"] = "sharpe_ratio",
    n_trials_debug: int = 20,
    aggressive_memory_management: bool = False,
    enhanced_monitoring: bool = True,
)
```

## IndicatorConfig

**Module:** `echolon.config.indicator_config`

**Purpose:** Technical indicator period caps (most users never override).

**Signature:**

```python
IndicatorConfig(
    interday_caps: dict[str, int],
    intraday_caps: dict[str, int],
)
```

## TradingContext

**Module:** `echolon.config.markets.core.context`

**Purpose:** Market + instrument + frequency runtime context.

**Classmethod:**

```python
TradingContext.from_market(
    market: str,           # e.g., "shfe"
    instrument: str,       # e.g., "cu"
    frequency: str = "interday",
    bar_size: str = "1d",
) -> TradingContext
```

## quick_start()

**Module:** `echolon`

**Purpose:** Build sensible default configs for common cases.

```python
from echolon import quick_start

ctx, bt, opt = quick_start(
    market="shfe",
    instrument="cu",
    start_date="2020-01-01",
    end_date="2023-12-31",
)
```

## EntrySignalOutput

**Module:** `echolon.quant_engine.types`

**Returned by:** `entry_rule.generate_signal()`

**Required fields:**
- `signal: Literal['LONG', 'SHORT', 'HOLD']`
- `strength: float` (0.0 to 1.0)
- `type: str`
- `entry_reason: str`
- `regime: str`

**Optional:**
- `intent: Optional[OrderIntent]` — required for non-HOLD signals

**Common errors:** VAL-001, VAL-002.

## ExitSignalOutput

**Returned by:** `exit_rule.should_exit()`

**Required fields:**
- `should_exit: bool`
- `exit_reason: str`
- `position_size: float` (≥ 0)
- `bars_since_entry: int` (≥ 0)

**Optional:**
- `intent: Optional[OrderIntent]` — required when `should_exit=True`

## RiskOutput

**Returned by:** `risk_manager.can_trade()`

**Required fields:**
- `trading_allowed: bool`
- `risk_reason: str`

## SizerOutput

**Returned by:** `position_sizer.calculate_size(signal_data)`

**Required fields:**
- `calculated_size: int` (≥ 0, whole contracts)
- `signal_direction: Literal['LONG', 'SHORT', 'HOLD']`
- `sizing_reason: str`
- `raw_size: float` (≥ 0)

## OrderIntent (enum)

**Module:** `echolon.quant_engine.core.interfaces.trading_interfaces`

**Values:**
- `ENTRY_LONG`, `ENTRY_SHORT`
- `EXIT_LONG`, `EXIT_SHORT`
- `FORCED_EXIT`
- `ROLLOVER_CLOSE`, `ROLLOVER_OPEN`

## EchelonError

**Module:** `echolon` (top-level) or `echolon.native.validation.errors`

**Base class** for all Echolon validation errors. Every error has `code`, `what`, `why`, `fix`, `context`, `docs_url`.

**Subclasses:**
- `ValidationError` (VAL-xxx)
- `ConfigError` (CFG-xxx)
- `StrategyStructureError` (STR-xxx)
- `IndicatorError` (IND-xxx)
- `ParameterError` (PRM-xxx)
- `DataError` (DAT-xxx)

See [ERROR_CATALOG.md](ERROR_CATALOG.md).
