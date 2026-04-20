"""PathsConfig — single source of truth for echolon directory layout.

A PyPI library must not bind its filesystem layout to the user's cwd at
import time. Callers construct one PathsConfig and inject it at the
library's public entry points (``run_data_pipeline``, ``run_backtest``,
``run_indicator_calculation``, etc.).

Typical usage from a host project (e.g. qorka)::

    from echolon.config.paths_config import PathsConfig
    paths = PathsConfig.from_project_root(Path(__file__).parent.parent)
    run_data_pipeline(ctx, paths=paths)

Or, for pip-installed end-users without a project layout::

    paths = PathsConfig.from_platformdirs("echolon")
"""
from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, model_validator


class PathsConfig(BaseModel):
    """Every directory and file path echolon writes to or reads from."""

    model_config = {"extra": "forbid"}

    # Root
    project_root: Path

    # Top-level
    session_dir: Path
    workspace_dir: Path
    output_dir: Path
    raw_data_dir: Path

    # Workspace → data
    market_data_dir: Path
    indicators_research_dir: Path
    indicators_backtest_dir: Path

    # Workspace → current iteration
    current_dir: Path
    strategy_code_dir: Path            # workspace/current/code
    backtest_results_dir: Path         # workspace/current/backtest
    current_analysis_dir: Path         # workspace/current/analysis

    # Specific files
    best_params_file: Path             # strategy_code_dir / "selected_robust_trial.json"
    deploy_config_file: Path           # session_dir / "deploy_config.json"

    @model_validator(mode="after")
    def _absolutise(self) -> "PathsConfig":
        for name in type(self).model_fields:
            value = getattr(self, name)
            if isinstance(value, Path) and not value.is_absolute():
                setattr(self, name, value.resolve())
        return self

    @classmethod
    def from_project_root(cls, project_root: Path | str, **overrides: Path | str) -> "PathsConfig":
        """Build from conventional <root>/{session,workspace,output,data} layout.

        Any field can be overridden by keyword (e.g. ``market_data_dir=...``).
        """
        root = Path(project_root).absolute()
        workspace = root / "workspace"
        indicators = workspace / "data" / "indicators"
        current = workspace / "current"
        strategy_code = current / "code"

        defaults: dict[str, Path] = {
            "project_root": root,
            "session_dir": root / "session",
            "workspace_dir": workspace,
            "output_dir": root / "output",
            "raw_data_dir": root / "data",
            "market_data_dir": workspace / "data" / "market_data",
            "indicators_research_dir": indicators / "research",
            "indicators_backtest_dir": indicators / "backtest",
            "current_dir": current,
            "strategy_code_dir": strategy_code,
            "backtest_results_dir": current / "backtest",
            "current_analysis_dir": current / "analysis",
            "best_params_file": strategy_code / "selected_robust_trial.json",
            "deploy_config_file": root / "session" / "deploy_config.json",
        }
        defaults.update({k: Path(v) for k, v in overrides.items()})
        return cls(**defaults)

    @classmethod
    def from_platformdirs(cls, app_name: str = "echolon") -> "PathsConfig":
        """Build using platformdirs (XDG on Linux, %APPDATA% on Windows).

        Requires the optional extra ``echolon[platformdirs]``. Suitable for
        pip-installed end-users without a project layout of their own.
        """
        try:
            from platformdirs import user_data_dir
        except ImportError as exc:
            raise ImportError(
                "PathsConfig.from_platformdirs requires the optional "
                "dependency `platformdirs`. Install it with "
                "`pip install echolon[platformdirs]` or `pip install platformdirs`."
            ) from exc
        return cls.from_project_root(user_data_dir(app_name, ensure_exists=False))
