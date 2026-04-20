"""Engine configuration — data paths and directory structure.

This file contains ONLY path configuration needed by the engine.
API keys and LLM configuration belong in the CLI product, not here.

All paths are derived from ECHOLON_PROJECT_ROOT (defaults to cwd) —
callers should prefer constructing an echolon.config.paths_config.PathsConfig
rather than importing these constants directly.
"""

import os
from pathlib import Path

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
