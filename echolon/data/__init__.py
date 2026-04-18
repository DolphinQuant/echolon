"""Echolon data pipeline — extractors, transformers, loaders, schemas."""

from echolon.data.run import run_data_pipeline

# Alias for the concise public name used in the top-level package.
run_pipeline = run_data_pipeline

__all__ = ["run_data_pipeline", "run_pipeline"]
