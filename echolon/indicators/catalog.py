"""Indicator catalog — programmatic introspection of indicators echolon ships.

Exposes:
  list_all(has_lookback=None)           -> list[str]
  info(name)                            -> IndicatorInfo | None
  validate(flat_dict)                   -> list[dict]   (error dicts, empty = valid)
  suggest_similar(name, limit=5)        -> list[str]
  auto_generate_list(strategy_dir)      -> dict          (placeholder stub)

Hydration happens at import time via `_load_from_registry()`, which walks
INDICATOR_MAPPING (interday) + INTRADAY_INDICATOR_MAPPING (intraday) and extracts
param defaults via ``inspect.signature`` on the calculator modules.

Phase F-5: ``cluster`` categorization removed. The previous 4-way split
(indicators_with_lookback / _without_lookback / _with_special_params /
intraday_context_indicators) is replaced by a single derived boolean
``IndicatorInfo.has_lookback`` — True when the indicator's signature has a
period-like parameter (``timeperiod`` / ``period`` / ``time_period``). This
collapses an artificial three-way distinction that was treating "no params"
and "multi params" identically at the runtime layer.

Merge rule: interday wins on name collision. The CTX passed at dispatch time
governs which calculator actually runs; catalog is frequency-agnostic.
"""
from __future__ import annotations

import difflib
import importlib
import inspect
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# Period-like parameter names — an indicator with one of these in its signature
# has "lookback" semantics (sweepable single-dim period). Same set as the
# processor uses for column-name suffix logic.
_PERIOD_PARAM_NAMES: frozenset = frozenset({
    "period", "timeperiod", "time_period",
})


@dataclass
class IndicatorInfo:
    """Structured metadata for one indicator entry."""

    name: str                  # lowercase canonical name (e.g. "rsi")
    function: str              # underlying function name in the calculator module
    file: str                  # calculator module name (e.g. "ta_lib")
    params: list[dict]         # [{"name": "timeperiod", "default": 14, "type": "int"}, ...]

    @property
    def has_lookback(self) -> bool:
        """True when the indicator has a period-like parameter (sweepable lookback).

        Derived from the function signature: if any param name is in
        ``_PERIOD_PARAM_NAMES`` (``timeperiod`` / ``period`` / ``time_period``),
        the indicator follows lookback semantics — runtime emits column names
        templated as ``{name}_{period_value}`` for single-period sweeps.

        Phase F-5 replacement for the previous ``cluster ==
        "indicators_with_lookback"`` check.
        """
        return any(p["name"] in _PERIOD_PARAM_NAMES for p in self.params)


# Reserved parameters stripped from inspect.signature() — these are plumbing,
# not user-tunable.
_RESERVED_PARAMS = {"df", "indicator_name", "ctx", "regime_params"}


def _type_name(value: Any) -> str:
    """Return a human-readable type name for a param default value."""
    if value is None:
        return "NoneType"
    return type(value).__name__


def _extract_params(func_name: str, file_name: str, is_intraday: bool) -> list[dict]:
    """Import the calculator module and extract user-tunable params.

    Returns ``[{"name": ..., "default": ..., "type": ...}, ...]``.
    Params in ``_RESERVED_PARAMS`` and VAR_POSITIONAL/VAR_KEYWORD are excluded.
    """
    subdir = "intraday" if is_intraday else "interday"
    try:
        module = importlib.import_module(
            f"echolon.indicators.calculators.{subdir}.{file_name}"
        )
    except ImportError:
        return []

    func = getattr(module, func_name, None)
    if func is None or not callable(func):
        return []

    try:
        sig = inspect.signature(func)
    except (ValueError, TypeError):
        return []

    params: list[dict] = []
    for param_name, param in sig.parameters.items():
        if param_name in _RESERVED_PARAMS:
            continue
        if param.kind in (
            inspect.Parameter.VAR_POSITIONAL,
            inspect.Parameter.VAR_KEYWORD,
        ):
            continue
        default = param.default if param.default is not inspect.Parameter.empty else None
        params.append({
            "name": param_name,
            "default": default,
            "type": _type_name(default),
        })
    return params


def _load_from_registry() -> dict[str, IndicatorInfo]:
    """Walk INDICATOR_MAPPING (interday) + INTRADAY_INDICATOR_MAPPING (intraday).

    Interday wins on collision: if the lowercase name already exists, skip the
    intraday entry. Intraday-only names (VWAP, session indicators, etc.)
    are added as new entries.

    Phase F-5: ``output_columns`` removed from IndicatorInfo (the static
    template lied for multi-param sweeps). Runtime column-naming via
    ``processor._build_suffix`` is the single source of truth — it correctly
    emits ``{name}_{period}`` for single-period sweeps and
    ``{name}_{key1}{val1}_{key2}{val2}`` for multi-param sweeps.
    """
    from echolon.indicators.calculators.interday.indicator_mapping import (
        INDICATOR_MAPPING,
    )
    from echolon.indicators.calculators.intraday.indicator_mapping import (
        INTRADAY_INDICATOR_MAPPING,
    )

    catalog: dict[str, IndicatorInfo] = {}

    def _ingest(mapping: dict, is_intraday: bool) -> None:
        for key, meta in mapping.items():
            name_lower = key.lower()
            if name_lower in catalog:
                continue
            func_name = meta["function"]
            file_name = meta.get("file", "ta_lib")
            catalog[name_lower] = IndicatorInfo(
                name=name_lower,
                function=func_name,
                file=file_name,
                params=_extract_params(func_name, file_name, is_intraday),
            )

    _ingest(INDICATOR_MAPPING, is_intraday=False)
    _ingest(INTRADAY_INDICATOR_MAPPING, is_intraday=True)
    return catalog


# Module-level catalog (built at import time).
_CATALOG: dict[str, IndicatorInfo] = _load_from_registry()


def list_all(has_lookback: bool | None = None) -> list[str]:
    """Return all known indicator names, sorted.

    Args:
        has_lookback: Optional filter.
            ``True``  → only indicators with a period-like parameter
                       (sweepable single-dim lookback).
            ``False`` → only indicators without a period parameter (no-param,
                       multi-param scalar, or special-config indicators).
            ``None``  → return all (default).

    Phase F-5: replaces the previous ``cluster=...`` keyword. The 4-way
    cluster split collapsed to a binary ``has_lookback`` because two of the
    three previous "non-lookback" categories were treated identically by
    every consumer.
    """
    if has_lookback is None:
        return sorted(_CATALOG.keys())
    return sorted(
        name for name, i in _CATALOG.items() if i.has_lookback == has_lookback
    )


def info(name: str) -> IndicatorInfo | None:
    """Return IndicatorInfo for a name (case-insensitive), or None if unknown."""
    if not name:
        return None
    return _CATALOG.get(name.lower())


def validate(flat_dict: dict) -> list[dict]:
    """Validate a flat-dict indicator specification against the catalog.

    Checks:
      (a) Every top-level key exists in the catalog (unknown name → IND-004).
      (b) Inner param keys are a subset of the indicator's catalog params
          (unknown param → IND-005).
      (c) For lookback indicators, ``[min, max]`` range must satisfy min <= max
          (violation → IND-006).

    Does NOT raise. Returns an empty list for a valid ``flat_dict``.

    Args:
        flat_dict: ``{indicator_name: {param: value_or_list}}``.
            Example: ``{"rsi": {"timeperiod": [10, 20]}, "obv": {}}``.

    Returns:
        List of error dicts with keys: ``code``, ``field``, ``message``, ``suggestion``.
    """
    # Phase G follow-up: Names registered as regime classifiers are valid
    # entries in indicator_list even though they aren't in the static
    # catalog. The processor (engine/processor.py) dispatches them via
    # `is_registered_classifier`; the validator must agree. Lazy-import to
    # match the `_load_from_registry` boundary already established here.
    from echolon.indicators.registry import is_registered_classifier

    errors: list[dict] = []

    for ind_name, params in flat_dict.items():
        ind_name_lower = ind_name.lower() if isinstance(ind_name, str) else ind_name
        indicator = _CATALOG.get(ind_name_lower)

        if indicator is None:
            if isinstance(ind_name_lower, str) and is_registered_classifier(ind_name_lower):
                continue
            suggestions = suggest_similar(str(ind_name_lower))
            msg = f"Unknown indicator '{ind_name}'. Run list_all() to see valid names."
            if suggestions:
                msg += f" Did you mean: {suggestions}?"
            errors.append({
                "code": "IND-004",
                "field": ind_name,
                "message": msg,
                "suggestion": suggestions,
            })
            continue

        if isinstance(params, dict) and params:
            known = {p["name"] for p in indicator.params}
            for param_key in params:
                if param_key not in known:
                    close = difflib.get_close_matches(
                        param_key, known, n=3, cutoff=0.6
                    )
                    msg = (
                        f"Unknown param '{param_key}' for indicator '{ind_name}'. "
                        f"Known params: {sorted(known)}."
                    )
                    if close:
                        msg += f" Did you mean: {close}?"
                    errors.append({
                        "code": "IND-005",
                        "field": f"{ind_name}.{param_key}",
                        "message": msg,
                        "suggestion": close,
                    })

        # Phase F-5: range validation now applies to ANY indicator's params
        # (was previously gated on cluster == "indicators_with_lookback",
        # which meant multi-param sweeps like {"bbands_upper": {"timeperiod":
        # [20, 10]}} silently skipped validation). The check is param-scoped
        # — any [min, max] integer list with min > max is an error regardless
        # of which indicator owns it.
        if isinstance(params, dict):
            for param_key, param_val in params.items():
                if (
                    isinstance(param_val, list)
                    and len(param_val) == 2
                    and all(isinstance(v, int) and not isinstance(v, bool) for v in param_val)
                ):
                    lo, hi = param_val
                    if lo > hi:
                        errors.append({
                            "code": "IND-006",
                            "field": f"{ind_name}.{param_key}",
                            "message": (
                                f"Invalid range for '{ind_name}.{param_key}': "
                                f"[{lo}, {hi}] — min ({lo}) must be <= max ({hi})."
                            ),
                            "suggestion": [],
                        })

    return errors


def suggest_similar(name: str, limit: int = 5) -> list[str]:
    """Return up to ``limit`` catalog names that are close matches to ``name``.

    Primary: ``difflib.get_close_matches`` with ``cutoff=0.6`` (handles typos).
    Fallback: substring containment — if the query contains a catalog name, or
    a catalog name contains the query, surface those too. Catches cases like
    ``"fake_rsi"`` → suggest ``"rsi"`` that difflib misses because the length
    mismatch drags the similarity ratio below the cutoff.
    """
    if not name:
        return []
    q = name.lower()
    keys = list(_CATALOG.keys())
    ranked = difflib.get_close_matches(q, keys, n=limit, cutoff=0.6)
    ranked_set = set(ranked)
    if len(ranked) < limit:
        for k in keys:
            if k in q or q in k:
                if k not in ranked_set:
                    ranked.append(k)
                    ranked_set.add(k)
                    if len(ranked) >= limit:
                        break
    return ranked[:limit]


def auto_generate_list(strategy_dir: Path) -> dict:
    """Scan strategy code for indicator usage; emit a canonical flat-dict list.

    Placeholder stub for Phase 1; full implementation in workstream E (Task 22).
    """
    return {}
