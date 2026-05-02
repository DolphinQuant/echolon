"""Registry for pluggable regime classifiers + optimizers.

Single-process, thread-safe. Consumers register at import time (built-in
:mod:`echolon.indicators.calculators.interday.market_regime`) or at session
startup (e.g., qorka calling its TRS setup). Echolon's pipeline looks up
classifiers/optimizers by name at runtime.

Echolon does NOT depend on any consumer. Registration is the only direction
of dependency — consumers call into echolon's registry, never vice-versa.

See :mod:`echolon.indicators.protocols` for the Protocol definitions.
"""
from __future__ import annotations
from typing import Dict, List
import threading

from echolon.indicators.protocols import (
    RegimeClassifier, RegimeClassifierOptimizer,
)


_LOCK = threading.RLock()
_CLASSIFIERS: Dict[str, RegimeClassifier] = {}
_OPTIMIZERS: Dict[str, RegimeClassifierOptimizer] = {}


def register_regime_classifier(classifier: RegimeClassifier) -> None:
    """Register (or replace) a classifier under its ``name`` attribute.

    Re-registering with the same name silently replaces the previous entry —
    convenient for testing and for hot-reloading classifier implementations.

    Args:
        classifier: Object conforming to :class:`RegimeClassifier` Protocol.
    """
    with _LOCK:
        _CLASSIFIERS[classifier.name] = classifier


def register_regime_optimizer(optimizer: RegimeClassifierOptimizer) -> None:
    """Register (or replace) an optimizer under its ``classifier_name`` attribute.

    Pairs with a classifier of the same name; one optimizer per classifier.

    Args:
        optimizer: Object conforming to :class:`RegimeClassifierOptimizer`.
    """
    with _LOCK:
        _OPTIMIZERS[optimizer.classifier_name] = optimizer


def get_regime_classifier(name: str) -> RegimeClassifier:
    """Look up a registered classifier. Raises ``KeyError`` if absent.

    Args:
        name: Classifier name to look up.

    Returns:
        The registered :class:`RegimeClassifier`.

    Raises:
        KeyError: If no classifier is registered under ``name``. The error
            message lists currently-registered classifier names.
    """
    with _LOCK:
        if name not in _CLASSIFIERS:
            registered = sorted(_CLASSIFIERS.keys())
            raise KeyError(
                f"No regime classifier registered under name={name!r}. "
                f"Registered: {registered}. "
                f"To add custom classifiers, call register_regime_classifier(...) "
                f"before invoking the indicator pipeline."
            )
        return _CLASSIFIERS[name]


def get_regime_optimizer(classifier_name: str) -> RegimeClassifierOptimizer:
    """Look up a registered optimizer for a classifier. Raises ``KeyError`` if absent.

    Args:
        classifier_name: Name of the classifier whose optimizer to look up.

    Returns:
        The registered :class:`RegimeClassifierOptimizer`.

    Raises:
        KeyError: If no optimizer is registered for ``classifier_name``.
            The error message points users to qorka's TRS setup for the
            common case.
    """
    with _LOCK:
        if classifier_name not in _OPTIMIZERS:
            registered = sorted(_OPTIMIZERS.keys())
            raise KeyError(
                f"No regime optimizer registered for classifier={classifier_name!r}. "
                f"Registered optimizers: {registered}. "
                f"For TRS rule-based optimization, install qorka and call "
                f"`from qorka.modules.paradigms.trs.regime_machinery import "
                f"setup_classifiers; setup_classifiers()` at session startup."
            )
        return _OPTIMIZERS[classifier_name]


def list_classifiers() -> List[str]:
    """Return sorted names of all registered classifiers."""
    with _LOCK:
        return sorted(_CLASSIFIERS.keys())


def list_optimizers() -> List[str]:
    """Return sorted classifier-names of all registered optimizers."""
    with _LOCK:
        return sorted(_OPTIMIZERS.keys())


def is_registered_classifier(name: str) -> bool:
    """Return True if ``name`` matches a registered classifier (case-insensitive).

    Used by the indicator pipeline to decide whether to dispatch via the
    classifier registry or fall through to the static ``indicator_mapping``.
    """
    with _LOCK:
        lower = name.lower()
        return any(k.lower() == lower for k in _CLASSIFIERS.keys())
