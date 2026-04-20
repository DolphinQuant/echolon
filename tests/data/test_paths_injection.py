"""Data-layer entry points must accept an injected PathsConfig."""
import inspect
import typing

from echolon.config.paths_config import PathsConfig
from echolon.data.backtest_data import run_data_pipeline
from echolon.data.live_data import run_live_data_update


def _accepts_paths(func) -> bool:
    sig = inspect.signature(func)
    if "paths" not in sig.parameters:
        return False
    annotation = sig.parameters["paths"].annotation
    # Accept either PathsConfig or Optional[PathsConfig] / PathsConfig | None.
    if annotation is PathsConfig:
        return True
    # PEP 604 or typing.Optional — get the non-None args.
    args = typing.get_args(annotation)
    return PathsConfig in args


def test_run_data_pipeline_accepts_paths():
    assert _accepts_paths(run_data_pipeline)


def test_run_live_data_update_accepts_paths():
    assert _accepts_paths(run_live_data_update)
