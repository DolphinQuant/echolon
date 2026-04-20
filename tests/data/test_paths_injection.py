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


def test_no_module_level_settings_import_in_extractors_markets_indicators():
    """Extractors, markets layer, and indicator optimizer must not import
    path constants from echolon.config.settings at module scope."""
    import ast
    import pathlib

    forbidden = {
        "RAW_DATA_DIR", "MARKET_DATA_DIR", "INDICATOR_DIR",
        "PROJECT_ROOT", "WORKSPACE_DIR", "OUTPUT_DIR", "SESSION_DIR",
        "INDICATORS_BACKTEST_DIR", "INDICATORS_RESEARCH_DIR",
        "PLATFORM_AGNOSTIC_DIR", "BEST_PARAMS_FILE", "BACKTEST_RESULTS_DIR",
        "STRATEGY_LOG_DIR", "DEPLOY_CONFIG_DIR",
    }
    base = pathlib.Path(__file__).resolve().parent.parent.parent / "echolon"
    targets = [
        base / "data" / "extractors",
        base / "markets",
        base / "indicators" / "optimization",
        base / "config" / "markets",
    ]
    offenders: list[tuple[str, list[str]]] = []
    for root in targets:
        for py in root.rglob("*.py"):
            tree = ast.parse(py.read_text())
            # Only top-level imports — function-scoped imports are fine (fallback pattern).
            for node in ast.iter_child_nodes(tree):
                if isinstance(node, ast.ImportFrom) and node.module == "echolon.config.settings":
                    leaked = sorted({alias.name for alias in node.names} & forbidden)
                    if leaked:
                        offenders.append((str(py.relative_to(base)), leaked))
    assert not offenders, f"module-level settings imports: {offenders}"


def test_no_module_level_settings_import_in_backtest_strategy_live():
    """backtest/, strategy/, live/ must not import path constants at module scope."""
    import ast
    import pathlib

    forbidden = {
        "RAW_DATA_DIR", "MARKET_DATA_DIR", "INDICATOR_DIR",
        "PROJECT_ROOT", "WORKSPACE_DIR", "OUTPUT_DIR", "SESSION_DIR",
        "INDICATORS_BACKTEST_DIR", "INDICATORS_RESEARCH_DIR",
        "PLATFORM_AGNOSTIC_DIR", "BEST_PARAMS_FILE", "BACKTEST_RESULTS_DIR",
        "STRATEGY_LOG_DIR", "DEPLOY_CONFIG_DIR",
    }
    base = pathlib.Path(__file__).resolve().parent.parent.parent / "echolon"
    offenders: list[tuple[str, list[str]]] = []
    for group in ("backtest", "strategy", "live"):
        for py in (base / group).rglob("*.py"):
            tree = ast.parse(py.read_text())
            for node in ast.iter_child_nodes(tree):
                if isinstance(node, ast.ImportFrom) and node.module == "echolon.config.settings":
                    leaked = sorted({alias.name for alias in node.names} & forbidden)
                    if leaked:
                        offenders.append((str(py.relative_to(base)), leaked))
    assert not offenders, f"module-level settings imports: {offenders}"
