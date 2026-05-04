"""File-format readers for strategy directory artifacts.

``calculator_params.json`` is the paradigm-blind file format for
classifier hyperparameters. It supports any registered classifier
(rule-based market regime, HMM, GMM, Carry term-structure, etc.) under
one schema.

File format (``calculator_params.json``)::

    {
      "version": 1,
      "calculators": {
        "market_regime": {
          "fast_ma_period": 12,
          "slow_ma_period": 30,
          "adx_period": 10,
          ...
        }
      }
    }
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional


_CALCULATOR_PARAMS_FILENAME = "calculator_params.json"


def load_calculator_params(strategy_dir: Path | str) -> Dict[str, Dict[str, Any]]:
    """Read calculator_params.json from a strategy directory.

    Args:
        strategy_dir: Path to the strategy directory containing the params file.

    Returns:
        Dict mapping calculator_name → params dict. Empty dict if the file
        is missing.
    """
    strategy_dir = Path(strategy_dir)
    path = strategy_dir / _CALCULATOR_PARAMS_FILENAME

    if path.exists():
        data = json.loads(path.read_text())
        version = data.get("version")
        if version == 1:
            return data.get("calculators", {}) or {}
        raise ValueError(
            f"Unknown calculator_params.json version: {version!r} in {path}"
        )

    return {}


def save_calculator_params(
    strategy_dir: Path | str,
    calculator_params: Dict[str, Dict[str, Any]],
) -> Path:
    """Write calculator_params.json in the v1 schema.

    Args:
        strategy_dir: Path to the strategy directory.
        calculator_params: Dict mapping calculator_name → params dict.

    Returns:
        Path to the written file.
    """
    strategy_dir = Path(strategy_dir)
    strategy_dir.mkdir(parents=True, exist_ok=True)
    out = strategy_dir / _CALCULATOR_PARAMS_FILENAME
    payload = {"version": 1, "calculators": calculator_params}
    out.write_text(json.dumps(payload, indent=2))
    return out


def get_regime_params(strategy_dir: Path | str) -> Optional[Dict[str, Any]]:
    """Convenience: extract just the ``market_regime`` calculator params.

    Equivalent to ``load_calculator_params(strategy_dir).get("market_regime")``.
    Returns ``None`` if the strategy has no regime classifier configured.
    """
    return load_calculator_params(strategy_dir).get("market_regime")
