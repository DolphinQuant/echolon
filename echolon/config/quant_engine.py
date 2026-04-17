"""
Quant Engine Configuration
==========================

Infrastructure paths and indicator-period caps only.

Business-logic configuration (backtest dates, IS/OOS split, WFA settings,
Optuna hyper-parameters, acceptable drawdown, etc.) now lives in typed
Pydantic configs:

- :class:`echolon.config.backtest_config.BacktestConfig`
- :class:`echolon.config.optuna_config.OptunaConfig`
- :class:`echolon.config.indicator_config.IndicatorConfig`
- ``echolon.quant_engine.backtest.wfa.window.WFAConfig``

Build them manually or via :func:`echolon.quick_start` for defaults.
"""
import os
from echolon.config.settings import (
    WORKSPACE_DIR,
    PROJECT_ROOT,
    MARKET_DATA_DIR as SETTINGS_MARKET_DATA_DIR,
    INDICATORS_BACKTEST_DIR,
)

# =============================================================================
# Directory Configuration (infrastructure paths, not business logic)
# =============================================================================
DEPLOY_CONFIG_DIR = os.path.join(
    PROJECT_ROOT, "session", "deploy_config.json"
)

# Backtest results (in workspace/current for current iteration)
BACKTEST_RESULTS_DIR = os.path.join(WORKSPACE_DIR, "current", "backtest")
STRATEGY_LOG_DIR = BACKTEST_RESULTS_DIR

# Strategy code directory — workspace location for generated strategy files.
# The coding agent writes here; the backtest engine reads via StrategyLoader.
PLATFORM_AGNOSTIC_DIR = os.path.join(WORKSPACE_DIR, "current", "code")

# Selected robust trial (optimized parameters) - lives with strategy code
BEST_PARAMS_FILE = os.path.join(PLATFORM_AGNOSTIC_DIR, "selected_robust_trial.json")

# Data directories (from centralized config)
MARKET_DATA_DIR = str(SETTINGS_MARKET_DATA_DIR)  # workspace/data/market_data/
INDICATOR_DIR = str(INDICATORS_BACKTEST_DIR)     # workspace/data/indicators/backtest/

# =============================================================================
# Indicator Period Caps (Interday - Daily Bars)
# =============================================================================
# Contracts have minimum 186 daily bars when becoming "main contract"
# Exceeding caps → NaN values → zero trades
INDICATOR_PERIOD_CAPS = {
    # Require ~3× period bars (max 62 for 186 bars)
    'tema': 62,
    'trix': 62,
    'adxr': 62,

    # Require ~2× period bars (max 93 for 186 bars)
    'adx': 93,
    'dema': 93,

    # Default cap for standard indicators (~1× period bars)
    'default': 180
}

# =============================================================================
# Indicator Period Caps (Intraday - Sub-daily Bars)
# =============================================================================
# For intraday data (e.g., SHFE 15-min with ~23 bars/day):
# 186 days × 23 bars/day = ~4,278 bars of history
# Caps can be much higher since we have many more bars
# NOTE: Period values are in BARS, not days
INTRADAY_INDICATOR_PERIOD_CAPS = {
    # Triple-smoothed indicators (3× lookback)
    # Max: 4278 / 3 ≈ 1426 for SHFE, but practical limit ~500
    'tema': 500,
    'trix': 500,
    'adxr': 500,

    # Double-smoothed indicators (2× lookback)
    'adx': 750,
    'dema': 750,

    # Standard indicators
    'default': 1000
}
