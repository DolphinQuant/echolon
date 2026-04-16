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
