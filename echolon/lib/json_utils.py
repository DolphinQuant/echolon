"""
JSON Serialization and File I/O Utilities

Provides robust JSON handling with numpy/pandas type conversion.
Used across all modules for saving analysis results.
"""

import json
import logging
import os
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


def ensure_dir_exists(dir_path: str) -> None:
    """
    Create directory if it doesn't exist.

    Parameters
    ----------
    dir_path : str
        Directory path to create
    """
    if not dir_path:
        return

    if not os.path.exists(dir_path):
        try:
            os.makedirs(dir_path)
            logger.info(f"Created directory: {dir_path}")
        except OSError as e:
            logger.error(f"Error creating directory {dir_path}: {e}")
            raise


def convert_for_json(obj: Any) -> Any:
    """
    Recursively convert numpy/pandas types to JSON-serializable Python types.

    Handles:
    - numpy integers/floats → Python int/float
    - numpy arrays → Python lists
    - pandas Series/DataFrame → lists/dicts
    - Dictionary keys that are numpy types

    Parameters
    ----------
    obj : Any
        Object to convert

    Returns
    -------
    Any
        JSON-serializable object
    """
    if isinstance(obj, dict):
        converted_dict = {}
        for key, value in obj.items():
            # Convert numpy keys to strings
            if isinstance(key, (np.integer, np.int64, np.int32)):
                str_key = str(int(key))
            elif isinstance(key, (np.floating, np.float64, np.float32)):
                str_key = str(float(key))
            else:
                str_key = str(key)
            converted_dict[str_key] = convert_for_json(value)
        return converted_dict

    elif isinstance(obj, list):
        return [convert_for_json(item) for item in obj]

    elif isinstance(obj, tuple):
        return [convert_for_json(item) for item in obj]

    elif isinstance(obj, (np.integer, np.int64, np.int32)):
        return int(obj)

    elif isinstance(obj, (np.floating, np.float64, np.float32)):
        return float(obj)

    elif isinstance(obj, (np.bool_, bool)):
        return bool(obj)

    elif isinstance(obj, np.ndarray):
        return obj.tolist()

    elif isinstance(obj, pd.Series):
        return obj.tolist()

    elif isinstance(obj, pd.DataFrame):
        return obj.to_dict('records')

    elif hasattr(obj, 'item'):  # Numpy scalar
        return obj.item()

    elif pd.isna(obj):
        return None

    else:
        return obj


def save_json(data: Any, filepath: str) -> None:
    """
    Save data to JSON file with comprehensive type conversion.

    Parameters
    ----------
    data : Any
        Data to save (dict, list, etc.)
    filepath : str
        Output file path
    """
    ensure_dir_exists(os.path.dirname(filepath))

    try:
        json_data = convert_for_json(data)

        with open(filepath, 'w') as f:
            json.dump(json_data, f, indent=4, ensure_ascii=False)

        logger.info(f"Results saved to {filepath}")

    except Exception as e:
        logger.error(f"Error saving to {filepath}: {e}")

        # Fallback with str conversion
        try:
            with open(filepath, 'w') as f:
                json.dump(data, f, indent=4, default=str, ensure_ascii=False)
            logger.info(f"Results saved to {filepath} using fallback method")
        except Exception as e2:
            logger.error(f"Fallback save also failed: {e2}")
            raise e2


def load_json(filepath: str) -> Any:
    """
    Load JSON file.

    Parameters
    ----------
    filepath : str
        Path to JSON file

    Returns
    -------
    Any
        Loaded data, or None if error
    """
    try:
        with open(filepath, 'r') as f:
            data = json.load(f)
        logger.info(f"Loaded JSON from: {filepath}")
        return data

    except FileNotFoundError:
        logger.error(f"File not found: {filepath}")
        return None

    except json.JSONDecodeError:
        logger.error(f"Invalid JSON in: {filepath}")
        return None

    except Exception as e:
        logger.error(f"Error loading {filepath}: {e}")
        return None


# Aliases for backward compatibility
save_results = save_json
