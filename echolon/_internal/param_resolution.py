"""Trial-parameter resolution — flat optuna params → nested component dicts.

The optimizer evaluates trials FRAMEWORK-NATIVELY: the generated
``optuna_search_space(trial)`` (shipped in every strategy dir's
strategy_params.py) writes sampled values directly onto canonical
component-dict keys and returns the complete nested
``{entry_params, exit_params, risk_params, sizer_params}`` dict. That nested
dict is transient — only the FLAT optuna-name dict survives into artifacts
(optimization_trials.csv → selected_robust_trial.json), and the historical
strip-once prefix mappers provably mangle it: single-prefixed canonical names
land on orphan keys nothing reads, bare names are dropped, and in-function
shared copies (e.g. sizer's mirror of exit stop mults) go stale.

``resolve_via_replay`` is the one AUTHORITATIVE resolver: replaying the
generated search space with ``optuna.trial.FixedTrial(flat_params)``
reproduces the optimizer's exact nested dict — FIXED params, crossover
constraints, and shared-parameter copies included, none of which a name-based
merge can recover.

``resolve_via_merge`` is a diagnostic FALLBACK only (audit logging when replay
fails; CI cross-checks on non-shared keys): a tiered name-aware merge that
handles canonical-name prefixing correctly but CANNOT recover shared copies —
its known limitation is asserted in tests, not worked around.
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger(__name__)

# Flat-name prefix → component dict key. Mirrors the historical mappers'
# vocabulary (trading_slot / BacktestRunner._map_optuna_params).
_PREFIX_TABLE = (
    ("entry_", "entry_params"),
    ("exit_", "exit_params"),
    ("risk_", "risk_params"),
    ("sizer_", "sizer_params"),
    ("size_", "sizer_params"),
)


def resolve_via_replay(
    search_space_fn: Callable[..., Dict[str, Any]],
    flat_params: Dict[str, Any],
) -> Optional[Dict[str, Dict[str, Any]]]:
    """Reproduce the optimizer's nested component dict for a recorded trial.

    Replays the generated ``optuna_search_space`` with a FixedTrial seeded from
    the flat params. Extra keys in ``flat_params`` (e.g. the exporter's legacy
    default-fill family) are simply never consumed — FixedTrial only looks up
    suggested names.

    Returns None (logged) when the replay cannot run: a suggested name missing
    from ``flat_params`` (ValueError), a crossover constraint pruning the trial
    (optuna.TrialPruned), or any other failure. Callers must fall back to the
    legacy path — never guess.
    """
    try:
        import optuna

        class _CastingFixedTrial(optuna.trial.FixedTrial):
            """FixedTrial that coerces CSV/JSON round-tripped values back to the
            distribution's type (pandas delivers 18.0 for an int suggestion)."""

            def suggest_int(self, name: str, *args: Any, **kwargs: Any) -> int:
                if name in self._params and self._params[name] is not None:
                    self._params[name] = int(round(float(self._params[name])))
                return super().suggest_int(name, *args, **kwargs)

            def suggest_float(self, name: str, *args: Any, **kwargs: Any) -> float:
                if name in self._params and self._params[name] is not None:
                    self._params[name] = float(self._params[name])
                return super().suggest_float(name, *args, **kwargs)

            def suggest_categorical(self, name: str, choices: Any) -> Any:
                # Canonicalize on ANY match (not only `value not in choices`):
                # cross-type equality means 10.0 passes a [10, 20] membership
                # test and FixedTrial would return the raw float — restore the
                # canonical choice object/type instead.
                if name in self._params:
                    value = self._params[name]
                    for choice in choices:
                        if choice == value or str(choice) == str(value):
                            self._params[name] = choice
                            break
                return super().suggest_categorical(name, choices)

        nested = search_space_fn(_CastingFixedTrial(dict(flat_params)))
    except Exception as exc:  # TrialPruned, ValueError(missing name), anything
        logger.warning(
            "[PARAM_RESOLUTION] replay failed (%s: %s) — caller must fall back",
            type(exc).__name__,
            exc,
        )
        return None

    if not isinstance(nested, dict) or not any(
        key.endswith("_params") for key in nested
    ):
        logger.warning(
            "[PARAM_RESOLUTION] replay returned unexpected shape %r — caller must fall back",
            type(nested).__name__,
        )
        return None
    return nested


def resolve_via_merge(
    flat_params: Dict[str, Any],
    default_params: Dict[str, Any],
) -> Dict[str, Dict[str, Any]]:
    """Tiered name-aware merge of flat trial params onto DEFAULT_PARAMS.

    FALLBACK / DIAGNOSTIC ONLY — cannot recover in-function shared copies
    (proven: ``apply_shared_params`` operates on canonical names, not flat
    ones, so e.g. sizer's mirror of an optimized exit stop stays at the
    default). Use ``resolve_via_replay`` for anything that deploys.

    Tiers per flat key (lowest tier wins on destination collision):
      1. the key itself is a member of its prefix's component dict
         (canonical name carries the component prefix — the generator's
         "avoid doubled prefix" naming);
      2. the key minus prefix is a member (legacy '{component}_{name}');
      3. bare key with UNIQUE membership across component dicts (catches
         e.g. zn's bare 'trailing_atr_multiplier' → sizer_params).
    Unmapped keys are logged and skipped, never raised.
    """
    components: Dict[str, Dict[str, Any]] = {
        key: dict(value)
        for key, value in default_params.items()
        if key.endswith("_params") and isinstance(value, dict)
    }
    placed_tier: Dict[tuple[str, str], int] = {}
    unmapped: list[str] = []

    def _place(comp: str, local: str, value: Any, tier: int) -> None:
        prior = placed_tier.get((comp, local))
        if prior is not None and prior <= tier:
            logger.debug(
                "[PARAM_RESOLUTION] merge: keeping tier-%d value for %s.%s "
                "(tier-%d duplicate ignored)",
                prior, comp, local, tier,
            )
            return
        components[comp][local] = value
        placed_tier[(comp, local)] = tier

    for key, value in flat_params.items():
        # Tier 1: canonical name already carries its component prefix.
        tier1 = next(
            (
                comp
                for prefix, comp in _PREFIX_TABLE
                if key.startswith(prefix) and comp in components and key in components[comp]
            ),
            None,
        )
        if tier1 is not None:
            _place(tier1, key, value, 1)
            continue
        # Tier 2: legacy '{component}_{name}' wrapping.
        tier2 = next(
            (
                (comp, key[len(prefix):])
                for prefix, comp in _PREFIX_TABLE
                if key.startswith(prefix)
                and comp in components
                and key[len(prefix):] in components[comp]
            ),
            None,
        )
        if tier2 is not None:
            _place(tier2[0], tier2[1], value, 2)
            continue
        # Tier 3: bare key with unique component membership.
        owners = [comp for comp, params in components.items() if key in params]
        if len(owners) == 1:
            _place(owners[0], key, value, 3)
            continue
        unmapped.append(key)

    if unmapped:
        logger.info(
            "[PARAM_RESOLUTION] merge: %d unmapped flat key(s): %s",
            len(unmapped),
            ", ".join(sorted(unmapped)[:10]),
        )
    return components
