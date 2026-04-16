# Quant Engine Schemas

This directory contains Pydantic BaseModel schemas that serve as **interface contracts** between `quant_engine` (producer) and `backtest_metrics` (consumer).

## Purpose

### Problems Solved
1. **Schema Drift**: No validation when quant_engine output format changes
2. **Fragile Dict Access**: 1,000+ unsafe dict accesses using `.get()` or `['key']`
3. **Silent Failures**: Errors discovered deep in analysis logic, not at load time
4. **No Documentation**: Data structure only existed in developers' minds

### Benefits
- ✅ **Fail-Fast Validation**: Errors caught at data load boundary
- ✅ **Type Safety**: IDE autocomplete and type checking
- ✅ **Living Documentation**: Schema IS the contract
- ✅ **Forward Compatibility**: `extra='allow'` supports new fields
- ✅ **Versioning**: Schema versions enable migrations

## Implemented Schemas

### 1. `backtest_results.py` - Backtest Results Schema v4.0

**Status**: ✅ IMPLEMENTED (2026-01-15)

**Producer**: `modules/quant_engine/backtest/engine/backtrader_engine.py`
**Consumer**: `modules/backtest_metrics/utils/backtest_loader.py`

**Schema Hierarchy**:
```
BacktestResultsSchemaV4
├── schema_version: str = "4.0"
├── run_timestamp: str
├── run_context: str
├── market: str
├── instrument: Optional[str]      # e.g., 'aluminum', 'bitcoin'
├── instrument_code: Optional[str] # e.g., 'al', 'btc'
└── performance_metrics: PerformanceMetricsSchema
    ├── sharpe_ratio_annual: float
    ├── total_return_pct: float
    ├── max_drawdown_pct: float
    ├── total_trades: int
    ├── ... (40+ fields)
    ├── trade_analyzer_details: Optional[TradeAnalyzerDetailsSchema]
    │   ├── total: TotalSchema
    │   ├── streak: StreakSchema
    │   ├── pnl: PnLSchema
    │   ├── won: TradeAnalyzerWonLostSchema
    │   ├── lost: TradeAnalyzerWonLostSchema
    │   ├── long: Optional[TradeAnalyzerDirectionSchema]
    │   ├── short: Optional[TradeAnalyzerDirectionSchema]
    │   └── len: Optional[TradeAnalyzerLengthStatsSchema]
    ├── time_drawdown: Optional[TimeDrawdownSchema]
    ├── period_stats: Optional[PeriodStatsSchema]
    └── daily_returns: Optional[Dict[str, float]]
```

**Breaking Changes from v3.0**:
- Renamed `sharpe_ratio` → `sharpe_ratio_annual`
- Added `trade_analyzer_details` nested structure
- Standardized field naming conventions

### 2. `trade_log.py` - Trade Log Schema v1.0

**Status**: ✅ IMPLEMENTED (2026-01-15)

**Producer**: `modules/quant_engine/backtest/engine/backtrader_engine.py`
**Consumer**: `modules/backtest_metrics/utils/backtest_loader.py`

**Schema**: TradeRecordSchema (30 columns)

**Column Categories**:

1. **REQUIRED FIELDS** (always present):
   - Entry/exit dates, times, prices
   - Direction (long/short), size
   - PnL fields (pnl, commission, pnlcomm, return_pct)
   - Exit reason

2. **CONDITIONAL FIELDS** (frequency-dependent):
   - **Interday only**: entry_regime
   - **Intraday only**: entry_session_phase, entry_session_type, session_id, entry_bar_of_session, exit_bar_of_session, total_bars_in_session

3. **OPTIONAL FIELDS** (may be missing):
   - MFE/MAE metrics: mfe_points, mae_points, mfe_pct, mae_pct, mfe_currency, mae_currency
   - Profit capture: profit_capture_rate, profit_left_on_table
   - Entry quality: entry_drawdown_points, entry_quality_score

**Validation Behavior**:
- Validates at CSV load time before DataFrame processing
- Returns DataFrame (not BaseModel) for analyzer compatibility
- Derived columns (hold_days, is_winner, year, month, etc.) added AFTER validation

**Key Features**:
- Handles both interday and intraday strategies
- Date/datetime parsing with proper validation
- Literal type for direction ('long' | 'short')
- Numeric constraints (size > 0, commission >= 0)

### 3. `selected_trial.py` - Selected Trial Schema v1.0

**Status**: ✅ IMPLEMENTED (2026-01-15)

**Producer**: `modules/quant_engine/backtest/optimization/trial_selector.py`
**Consumer**: `modules/backtest_metrics/utils/backtest_loader.py`

**Schema**: SelectedTrialSchema

**Structure**:
```
SelectedTrialSchema
├── trial_number: int (Optuna trial number)
├── selection_reason: str (Why this trial was selected)
├── cluster_id: int (Parameter cluster ID)
├── cluster_robustness_score: float (-1 to 1)
├── parameter_stability_score: float (0 to 1)
├── metrics: TrialMetricsSchema
│   ├── sharpe_ratio: float
│   ├── annual_return: float
│   └── max_drawdown_pct: float
└── params: Dict[str, Any] (Strategy parameters)
```

**Helper Methods**:
- `get_param(key, default)` - Get parameter with optional default
- `get_period_params()` - Extract period parameters (e.g., `{'atr': 15}`)

**Access Patterns**:
- `loader.selected_trial` - Full SelectedTrialSchema with metadata
- `loader.strategy_params` - Dict[str, Any] (backward compatible)

### 4. `strategy_log.py` - Strategy Log Schema v1.0

**Status**: ✅ IMPLEMENTED (2026-01-15)

**Producer**: `modules/quant_engine/backtest/engine/analyzers.py` (StrategyLog analyzer)
**Consumer**: `modules/backtest_metrics/utils/backtest_loader.py`

**File**: `Bridge_default.csv` (where 'default' is strategy instance name)

**Schema**: StrategyLogRecordSchema (28 columns)

**Column Categories**:

1. **Bar Metadata**: datetime, bar_count
2. **Entry Component**: entry_signal, entry_strength, entry_type, entry_reason, entry_regime
3. **Exit Component**: exit_should_exit, exit_reason, exit_position_size, exit_bars_since_entry
4. **Sizing Component**: sizing_calculated_size, sizing_raw_size, sizing_signal_direction, sizing_reason
5. **Risk Component**: risk_trading_allowed, risk_reason
6. **Order Management**: order_action, order_side, order_size, order_status, order_ref, order_executed
7. **Execution Details**: execution_date, execution_price, execution_size
8. **Forced Exit**: is_forced_exit, forced_exit_reason

**Key Fields**:
- `entry_signal`: Literal['HOLD', 'LONG', 'SHORT']
- `entry_strength`: float (0.0 to 1.0)
- `exit_should_exit`: bool
- `risk_trading_allowed`: bool
- `is_forced_exit`: bool

**Validation Functions**:
- `validate_strategy_log_dataframe(records)` - Returns list[StrategyLogRecordSchema]
- `validate_strategy_log_dict_list(records)` - Returns list[dict]

## Usage

### Consumer Side (backtest_metrics)

#### Backtest Results Usage

**Before (Dict Access - REMOVED)**:
```python
# OLD: Unsafe dict access
results = json.load(f)
sharpe = results['performance_metrics']['sharpe_ratio_annual']
trades = results['performance_metrics'].get('total_trades', 0)
```

**After (BaseModel Access - IMPLEMENTED)**:
```python
from modules.quant_engine.schemas.backtest_results import BacktestResultsSchemaV4

# Load and validate
raw_data = json.load(f)
validated = BacktestResultsSchemaV4(**raw_data)  # Validates schema

# Type-safe attribute access
sharpe = validated.performance_metrics.sharpe_ratio_annual
trades = validated.performance_metrics.total_trades

# Nested access
longest_win_streak = validated.performance_metrics.trade_analyzer_details.streak.won.longest
```

#### Trade Log Usage

**Implementation** (in backtest_loader.py):
```python
from modules.quant_engine.schemas.trade_log import validate_trade_log_dataframe

# Load CSV
df = pd.read_csv('backtest_trades.csv')

# Validate all trades
trades_dict = df.to_dict('records')
validated_trades = validate_trade_log_dataframe(trades_dict)  # Validates schema

# Continue with DataFrame processing
# ... (date conversions, derived columns, etc.)

# Analyzers use DataFrame normally
winners = df[df['is_winner'] == True]
avg_pnl = df['pnl'].mean()
```

**Key Difference from backtest_results**:
- backtest_results: Returns BaseModel → analyzers use attribute access
- trade_log: Validates then returns DataFrame → analyzers use DataFrame operations

#### Selected Trial Usage

**Implementation** (in backtest_loader.py):
```python
# Full trial with metadata (SelectedTrialSchema)
trial = loader.selected_trial
print(f"Trial #{trial.trial_number} from cluster {trial.cluster_id}")
print(f"Sharpe: {trial.metrics.sharpe_ratio:.4f}")

# Helper methods
period_params = trial.get_period_params()  # {'atr': 15}
atr_period = trial.get_param('exit_atr_period', 14)  # With default

# Backward compatible (Dict[str, Any])
params = loader.strategy_params
for key, value in params.items():
    print(f"  {key}: {value}")
```

**Key Difference**:
- `selected_trial`: Full SelectedTrialSchema with trial metadata + metrics + params
- `strategy_params`: Dict[str, Any] (just the params dict for backward compatibility)

### Producer Side (quant_engine)

**Optional Validation** (controlled by environment variable):
```python
import os
from modules.quant_engine.schemas.backtest_results import BacktestResultsSchemaV4

VALIDATE_OUTPUT = os.getenv('VALIDATE_QUANT_ENGINE_OUTPUT', 'false') == 'true'

def save_backtest_results(results: Dict[str, Any], output_path: str):
    # Add schema version
    if 'schema_version' not in results:
        results['schema_version'] = '4.0'

    # Optional validation (dev only)
    if VALIDATE_OUTPUT:
        try:
            validated = BacktestResultsSchemaV4(**results)
            results = validated.model_dump()
            logger.info("✅ Validated against schema v4.0")
        except ValidationError as e:
            logger.error(f"❌ Schema validation failed:\n{e}")
            logger.warning("Saving unvalidated (graceful degradation)")

    with open(output_path, 'w') as f:
        json.dump(results, f, indent=2)
```

## Migration Status

### Completed (Priority 1 - CRITICAL)
- ✅ **Schema definition: `backtest_results.py` (v4.0)**
  - 40+ performance metrics with nested structures
  - TradeAnalyzerDetails with 6 nested schemas
  - Optional fields for forward compatibility
- ✅ **Schema definition: `trade_log.py` (v1.0)**
  - 30 columns with frequency-aware validation
  - Handles both interday and intraday strategies
  - MFE/MAE, profit capture, entry quality metrics
- ✅ **Schema definition: `selected_trial.py` (v1.0)**
  - Trial metadata (trial_number, cluster_id, selection_reason)
  - Performance metrics (sharpe, annual_return, max_drawdown)
  - Strategy parameters with helper methods
- ✅ **Schema definition: `strategy_log.py` (v1.0)**
  - Bar-by-bar strategy decision log (28 columns)
  - Entry/exit/sizing/risk component outputs
  - Order management and execution details
- ✅ **Loader integration: `backtest_loader.py`**
  - `load_backtest_results()` returns BacktestResultsSchemaV4
  - `load_trades()` validates TradeRecordSchema
  - `load_selected_trial()` returns SelectedTrialSchema
  - `strategy_params` property for backward compatibility
  - Fail-fast validation at module boundary
- ✅ **Type hints updated: `base_analyzer.py` signature**
- ✅ **Analyzer migrations**:
  - `executive_performance_analysis.py` (6 dict accesses → attribute access)
  - `session_risk_analyzer.py` (1 dict access → attribute access)
  - `position_sizing_analyzer.py` (no changes needed)
  - `temporal_performance_evolution.py` (no changes needed)
  - `trade_frequency_analysis.py` (no changes needed)
  - `optuna_robustness_analysis.py` (trial_results removed - dead code)

### Testing
- ✅ Schema validation test: `test_backtest_schema.py` (backtest_results)
- ✅ Schema validation test: `test_trade_schema.py` (trade_log)
- ✅ Integration test: `test_backtest_loader_integration.py` (both schemas)
- ✅ Integration test: `test_integrated_loader.py` (all 3 schemas + DataFrame ops)
- ✅ All 192 trades validate successfully
- ✅ Selected trial validates with helper methods working
- ✅ All tests passing

## Future Work

### Priority 1 (Recommended)
- [ ] Producer validation in `backtrader_engine.py` (optional, env-controlled)

### Priority 2 (Optional)
- [ ] Implement `equity_curve.py` schema (simple: date, value)

### Priority 3 (Skip)
- ❌ `optimization_trials.csv` - Owned by Optuna library
- ❌ `trading_target.json` - User input, stable format
- ❌ `trial_results.json` - Removed (dead code)

## Versioning Strategy

### Semantic Versioning
- **MAJOR.MINOR** format (e.g., 4.0, 4.1, 5.0)
- **MAJOR**: Breaking changes (field removed, type changed)
- **MINOR**: Additive changes (new field, relaxed constraint)

### Migration Support
```python
# modules/backtest_metrics/utils/schema_migrations.py
def migrate_backtest_results(raw_data: Dict[str, Any]) -> Dict[str, Any]:
    """Migrate to latest schema version."""
    version = raw_data.get('schema_version', '3.0')

    if version == '3.0':
        raw_data = migrate_v3_to_v4(raw_data)
        version = '4.0'

    if version == '4.0':
        return raw_data

    raise ValueError(f"Unsupported version: {version}")
```

## Design Principles

1. **Single Source of Truth**: Schema lives in `quant_engine/schemas/`
2. **Fail-Fast**: Always validate at module boundaries
3. **Forward Compatibility**: Use `extra='allow'` in BaseModel config
4. **Type Safety**: Strict typing for required fields, Optional for optional fields
5. **No Backward Compat Hacks**: Delete unused fields completely

## Performance Impact

### Validation Overhead
- **Pydantic validation**: ~100-150ms per backtest_results.json load
- **Memory**: Negligible (validated once at load boundary)
- **Trade-off**: Acceptable for 80% error detection benefit

### Comparison
```
Without validation: Load + fail deep in analyzer = waste 5-10 minutes
With validation:    Load + fail immediately = save 5-10 minutes
```

## References

- [Pydantic Documentation](https://docs.pydantic.dev/)
- [SHARED_SCHEMA_ARCHITECTURE.md](../../modules/backtest_metrics/SHARED_SCHEMA_ARCHITECTURE.md)
- [BASEMODEL_IMPLEMENTATION_STRATEGY.md](../../modules/backtest_metrics/BASEMODEL_IMPLEMENTATION_STRATEGY.md)
