"""Engine configuration — data paths and directory structure.

This file contains ONLY path configuration needed by the engine.
API keys and LLM configuration belong in the CLI product, not here.

All paths are configurable via environment variables with sensible defaults.
Set ECHOLON_PROJECT_ROOT to override the project root (defaults to cwd).
"""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# =============================================================================
# Project Root
# =============================================================================
PROJECT_ROOT = Path(os.getenv("ECHOLON_PROJECT_ROOT", Path.cwd())).absolute()

# =============================================================================
# Top-Level Directories
# =============================================================================
SESSION_DIR = PROJECT_ROOT / "session"
WORKSPACE_DIR = PROJECT_ROOT / "workspace"
OUTPUT_DIR = PROJECT_ROOT / "output"
RAW_DATA_DIR = PROJECT_ROOT / "data"

# =============================================================================
# Workspace Data Directories
# =============================================================================
MARKET_DATA_DIR = WORKSPACE_DIR / "data" / "market_data"

INDICATORS_DIR = WORKSPACE_DIR / "data" / "indicators"
INDICATORS_RESEARCH_DIR = INDICATORS_DIR / "research"
INDICATORS_BACKTEST_DIR = INDICATORS_DIR / "backtest"

CURRENT_DIR = WORKSPACE_DIR / "current"
CURRENT_ANALYSIS_DIR = CURRENT_DIR / "analysis"


# =============================================================================
# Convenience getter functions (for dynamic resolution)
# =============================================================================
def get_workspace_dir() -> Path:
    """Return workspace directory, configurable via DOLPHIN_WORKSPACE env var."""
    workspace = os.getenv("DOLPHIN_WORKSPACE", str(WORKSPACE_DIR))
    return Path(workspace)


def get_data_dir() -> Path:
    """Return data directory, configurable via DOLPHIN_DATA_DIR env var."""
    data_dir = os.getenv("DOLPHIN_DATA_DIR", str(RAW_DATA_DIR))
    return Path(data_dir)


def get_dataset_dir() -> Path:
    """Return dataset directory, configurable via DOLPHIN_DATASET_DIR env var."""
    dataset_dir = os.getenv("DOLPHIN_DATASET_DIR", "dataset")
    return Path(dataset_dir)


# =============================================================================
# Quant Engine Infrastructure Paths
# =============================================================================
# Business-logic configuration (backtest dates, IS/OOS split, WFA settings,
# Optuna hyper-parameters, acceptable drawdown, etc.) lives in typed
# Pydantic configs:
#
# - echolon.config.backtest_config.BacktestConfig
# - echolon.config.optuna_config.OptunaConfig
# - echolon.config.indicator_config.IndicatorConfig
# - echolon.backtest.wfa.window.WFAConfig
#
# Build them manually or via echolon.quick_start for defaults.

DEPLOY_CONFIG_DIR = os.path.join(
    str(PROJECT_ROOT), "session", "deploy_config.json"
)

# Backtest results (in workspace/current for current iteration)
BACKTEST_RESULTS_DIR = os.path.join(str(WORKSPACE_DIR), "current", "backtest")
STRATEGY_LOG_DIR = BACKTEST_RESULTS_DIR

# Strategy code directory - workspace location for generated strategy files.
# The coding agent writes here; the backtest engine reads via StrategyLoader.
PLATFORM_AGNOSTIC_DIR = os.path.join(str(WORKSPACE_DIR), "current", "code")

# Selected robust trial (optimized parameters) - lives with strategy code
BEST_PARAMS_FILE = os.path.join(PLATFORM_AGNOSTIC_DIR, "selected_robust_trial.json")

# Indicator directory alias (MARKET_DATA_DIR already defined above as Path)
INDICATOR_DIR = str(INDICATORS_BACKTEST_DIR)     # workspace/data/indicators/backtest/


# =============================================================================
# Indicator Period Caps (Interday - Daily Bars)
# =============================================================================
# Contracts have minimum 186 daily bars when becoming "main contract"
# Exceeding caps -> NaN values -> zero trades
INDICATOR_PERIOD_CAPS = {
    # Require ~3x period bars (max 62 for 186 bars)
    'tema': 62,
    'trix': 62,
    'adxr': 62,

    # Require ~2x period bars (max 93 for 186 bars)
    'adx': 93,
    'dema': 93,

    # Default cap for standard indicators (~1x period bars)
    'default': 180
}

# =============================================================================
# Indicator Period Caps (Intraday - Sub-daily Bars)
# =============================================================================
# For intraday data (e.g., SHFE 15-min with ~23 bars/day):
# 186 days x 23 bars/day = ~4,278 bars of history
# Caps can be much higher since we have many more bars
# NOTE: Period values are in BARS, not days
INTRADAY_INDICATOR_PERIOD_CAPS = {
    # Triple-smoothed indicators (3x lookback)
    # Max: 4278 / 3 ~= 1426 for SHFE, but practical limit ~500
    'tema': 500,
    'trix': 500,
    'adxr': 500,

    # Double-smoothed indicators (2x lookback)
    'adx': 750,
    'dema': 750,

    # Standard indicators
    'default': 1000
}
