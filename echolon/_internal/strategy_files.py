"""File-format readers for strategy directory artifacts.

Phase E paradigm-decoupling: ``calculator_params.json`` is the
paradigm-blind successor to ``regime_params.json``. The new file format
supports any registered classifier (market_regime, future HMM, future
Carry term-structure) under one schema; legacy ``regime_params.json``
files auto-migrate on load so existing strategies in
``output_bank/`` continue to work without manual intervention.

New file format (``calculator_params.json``)::

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

Legacy file format (``regime_params.json``) — auto-migrated::

    {"params": {"fast_ma_period": 12, ...}}    # wrapped form
    {"fast_ma_period": 12, ...}                # flat form

Both legacy shapes are read into ``calculators["market_regime"]``.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional


_CALCULATOR_PARAMS_FILENAME = "calculator_params.json"
_LEGACY_REGIME_PARAMS_FILENAME = "regime_params.json"


def load_calculator_params(strategy_dir: Path | str) -> Dict[str, Dict[str, Any]]:
    """Read calculator_params.json (or auto-migrate legacy regime_params.json).

    Args:
        strategy_dir: Path to the strategy directory containing the params file.

    Returns:
        Dict mapping calculator_name → params dict. Empty dict if neither
        file is present.

    Examples::

        params = load_calculator_params(Path("output_bank/cu_1d_200_1"))
        regime_params = params.get("market_regime")  # back-compat accessor
    """
    strategy_dir = Path(strategy_dir)
    new_path = strategy_dir / _CALCULATOR_PARAMS_FILENAME

    if new_path.exists():
        data = json.loads(new_path.read_text())
        version = data.get("version")
        if version == 1:
            return data.get("calculators", {}) or {}
        # Future schema versions → handle here

    legacy_path = strategy_dir / _LEGACY_REGIME_PARAMS_FILENAME
    if legacy_path.exists():
        legacy_data = json.loads(legacy_path.read_text())
        # Two legacy shapes:
        #   {"params": {...}}  (wrapped — qorka-generated)
        #   {...}              (flat — early hand-rolled)
        inner = legacy_data.get("params", legacy_data)
        return {"market_regime": inner}

    return {}


def save_calculator_params(
    strategy_dir: Path | str,
    calculator_params: Dict[str, Dict[str, Any]],
) -> Path:
    """Write calculator_params.json in the new schema.

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
