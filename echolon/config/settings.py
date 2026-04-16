"""Engine configuration — data paths and directory structure.

This file contains ONLY path configuration needed by the engine.
API keys and LLM configuration belong in the CLI product, not here.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def get_workspace_dir() -> Path:
    """Return workspace directory, configurable via DOLPHIN_WORKSPACE env var."""
    workspace = os.getenv("DOLPHIN_WORKSPACE", "workspace")
    return Path(workspace)


def get_data_dir() -> Path:
    """Return data directory, configurable via DOLPHIN_DATA_DIR env var."""
    data_dir = os.getenv("DOLPHIN_DATA_DIR", "data")
    return Path(data_dir)


def get_dataset_dir() -> Path:
    """Return dataset directory, configurable via DOLPHIN_DATASET_DIR env var."""
    dataset_dir = os.getenv("DOLPHIN_DATASET_DIR", "dataset")
    return Path(dataset_dir)
