"""Load flat-dict indicator configs from disk.

Flat-dict format (per echolon/indicators/schema.py::IndicatorList):

    {"<indicator_name>": {"<param>": scalar | list}, ...}
"""
from __future__ import annotations

import json
from typing import Any, Dict


def load_indicator_list(path: str) -> Dict[str, Any]:
    """Load a ``strategy_indicator_list.json`` file as flat-dict.

    Validates against the catalog via
    :class:`echolon.indicators.schema.IndicatorList` — unknown names or shapes
    fail fast before the caller touches the result.
    """
    from echolon.indicators.schema import IndicatorList

    with open(path, "r") as f:
        data = json.load(f)
    IndicatorList.model_validate(data)
    return data
