"""Echolon strategy code generators.

Currently ships two generators:

- :func:`generate_strategy_params` — deterministic Python-code generation of
  ``strategy_params.py`` from a ``params_to_optimize.json`` input. Exposed
  as the ``generate_strategy_params`` tool on the echolon-mcp server.

- :func:`generate_entry` — scaffolding generator for ``entry.py`` component
  stub. Produces a framework-correct minimal entry rule that returns HOLD by
  default — coding agents refine into real pathways.
"""
from echolon.strategy.generators.entry_generator import generate_entry
from echolon.strategy.generators.strategy_params_generator import (
    GenerationResult,
    StrategyParamsGenerator,
    generate_strategy_params,
)

__all__ = [
    "GenerationResult",
    "StrategyParamsGenerator",
    "generate_strategy_params",
    "generate_entry",
]
