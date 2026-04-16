"""
Quant Engine Configuration
==========================

Backtest parameters, optimization settings, and data directories.
"""
import os
from config.settings import (
    WORKSPACE_DIR,
    PROJECT_ROOT,
    MARKET_DATA_DIR as SETTINGS_MARKET_DATA_DIR,
    INDICATORS_BACKTEST_DIR,
)

# =============================================================================
# Backtest Parameters
# =============================================================================
BACKTEST_START_DATE = "2018-01-01"
BACKTEST_END_DATE = "2025-12-31"

# =============================================================================
# IS/OOS Data Split (Optuna optimization vs out-of-sample validation)
# =============================================================================
# In-Sample: Optuna optimizes parameters on this period
OPTIMIZATION_START_DATE = BACKTEST_START_DATE   # "2021-01-01"
OPTIMIZATION_END_DATE = "2022-12-31"            # 3 years IS

# Out-of-Sample: Best trial validated on this unseen period
OOS_START_DATE = "2023-01-01"                   # 2 years OOS
OOS_END_DATE = BACKTEST_END_DATE                # "2025-12-31"

# =============================================================================
# Walk-Forward Analysis (WFA) Configuration
# =============================================================================
WFA_ENABLED = True  # False = legacy single IS/OOS split

# Anchored (expanding) windows: IS always starts from BACKTEST_START_DATE
WFA_WINDOWS = [
    {"window_id": 1, "is_start": "2018-01-01", "is_end": "2020-12-31", "oos_start": "2021-01-01", "oos_end": "2021-12-31"},
    {"window_id": 2, "is_start": "2018-01-01", "is_end": "2021-12-31", "oos_start": "2022-01-01", "oos_end": "2022-12-31"},
    {"window_id": 3, "is_start": "2018-01-01", "is_end": "2022-12-31", "oos_start": "2023-01-01", "oos_end": "2023-12-31"},
    {"window_id": 4, "is_start": "2018-01-01", "is_end": "2023-12-31", "oos_start": "2024-01-01", "oos_end": "2024-12-31"},
    {"window_id": 5, "is_start": "2018-01-01", "is_end": "2024-12-31", "oos_start": "2025-01-01", "oos_end": "2025-12-31"},
]

WFA_TRIALS_PER_WINDOW = 200  # 200 x 5 = 1000 total trials

# Market research data cutoff: None = use full sample (2018-2025).
# IC-based indicator selection is a coarse categorical choice (~30 candidates)
# with negligible overfitting risk. Full-sample IC gives more accurate factor
# rankings that reflect current market structure, while WFA+DRS provide the
# real overfitting defense at the parameter optimization level.
MARKET_RESEARCH_END_DATE = None

# =============================================================================
# Optuna Parameter Selection
# =============================================================================
ACCEPTABLE_MAX_DRAWDOWN_PCT = 15.0  # Max drawdown for Pareto frontier selection

# =============================================================================
# Directory Configuration
# =============================================================================
DEPLOY_CONFIG_DIR = os.path.join(
    PROJECT_ROOT, "session", "deploy_config.json"
)

# Backtest results (in workspace/current for current iteration)
BACKTEST_RESULTS_DIR = os.path.join(WORKSPACE_DIR, "current", "backtest")
STRATEGY_LOG_DIR = BACKTEST_RESULTS_DIR

# Strategy code directory
PLATFORM_AGNOSTIC_DIR = os.path.join(
    PROJECT_ROOT, "modules", "quant_engine", "strategy", "platform_agnostic"
)

# Selected robust trial (optimized parameters) - lives with strategy code
BEST_PARAMS_FILE = os.path.join(PLATFORM_AGNOSTIC_DIR, "selected_robust_trial.json")

# Data directories (from centralized config)
MARKET_DATA_DIR = str(SETTINGS_MARKET_DATA_DIR)  # workspace/data/market_data/
INDICATOR_DIR = str(INDICATORS_BACKTEST_DIR)     # workspace/data/indicators/backtest/

# --- Optuna Hyperparameter Optimization ---
OPTUNA_TRIALS = 400 # Increased number of trials for better optimization
OPTUNA_TRIALS_DEBUG = 200
OPTUNA_N_JOBS = -1      # Number of parallel jobs (-1 uses all available CPU cores, will be optimized dynamically)
OPTUNA_TIMEOUT = None   # No timeout, to ensure all trials are completed
# OPTUNA_EARLY_STOPPING = 1000  # Disabled as requested
OPTUNA_OPTIMIZATION_TARGET = "multi_objective"  # Options: "sharpe_ratio", "total_return", "annual_return", "drawdown", "multi_objective"
OPTUNA_AGGRESSIVE_MEMORY_MANAGEMENT = True  # Enable aggressive memory cleanup
OPTUNA_ENHANCED_MONITORING = True       # Enable detailed progress monitoring

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