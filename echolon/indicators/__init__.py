"""
Indicators Module
=================

Technical indicator calculation engine.

Public surfaces:

- ``catalog`` — indicator metadata + registration table (paradigm-blind).
- ``register_regime_classifier`` / ``register_regime_optimizer`` — register
  custom classifiers/optimizers. Echolon ships **zero built-in classifiers**
  as of Phase G; consumers (qorka for TRS, user code for HMM / Carry / etc.)
  register their own.
- ``get_regime_classifier`` / ``get_regime_optimizer`` — registry lookup.
- ``list_classifiers`` / ``list_optimizers`` — introspection.

See :mod:`echolon.indicators.protocols` for the Protocol definitions.

**Phase D** removed the legacy ``optimize_regime_params`` wrapper (TRS
optimizer moved to qorka). **Phase G** removed the legacy built-in
``market_regime`` classifier (TRS classifier moved to qorka). Install qorka
and call ``modules.paradigms.trs.regime_machinery.setup_classifiers()``
at session start; the classifier + optimizer are then accessible via
``echolon.indicators.get_regime_classifier("market_regime")`` and
``echolon.indicators.get_regime_optimizer("market_regime")``.
"""
from echolon.indicators import catalog

# Classifier registry — extension point for paradigm-specific machinery.
from echolon.indicators.registry import (
    register_regime_classifier,
    register_regime_optimizer,
    get_regime_classifier,
    get_regime_optimizer,
    list_classifiers,
    list_optimizers,
)

__all__ = [
    "catalog",
    "register_regime_classifier",
    "register_regime_optimizer",
    "get_regime_classifier",
    "get_regime_optimizer",
    "list_classifiers",
    "list_optimizers",
]
