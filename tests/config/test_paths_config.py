"""PathsConfig — single source of truth for library-owned directory layout."""
from pathlib import Path

import pytest
from pydantic import ValidationError

from echolon.config.paths_config import PathsConfig


def test_from_project_root_conventional_layout(tmp_path: Path):
    paths = PathsConfig.from_project_root(tmp_path)
    assert paths.project_root == tmp_path.resolve()
    assert paths.session_dir == tmp_path / "session"
    assert paths.workspace_dir == tmp_path / "workspace"
    assert paths.output_dir == tmp_path / "output"
    assert paths.raw_data_dir == tmp_path / "data"
    assert paths.market_data_dir == tmp_path / "workspace" / "data" / "market_data"
    assert paths.indicators_research_dir == tmp_path / "workspace" / "data" / "indicators" / "research"
    assert paths.indicators_backtest_dir == tmp_path / "workspace" / "data" / "indicators" / "backtest"
    assert paths.current_dir == tmp_path / "workspace" / "current"
    assert paths.strategy_code_dir == tmp_path / "workspace" / "current" / "code"
    assert paths.backtest_results_dir == tmp_path / "workspace" / "current" / "backtest"
    assert paths.best_params_file == tmp_path / "workspace" / "current" / "code" / "selected_robust_trial.json"
    assert paths.deploy_config_file == tmp_path / "session" / "deploy_config.json"


def test_explicit_override(tmp_path: Path):
    paths = PathsConfig.from_project_root(
        tmp_path,
        market_data_dir=tmp_path / "custom_md",
    )
    assert paths.market_data_dir == tmp_path / "custom_md"
    # Non-overridden stays conventional
    assert paths.raw_data_dir == tmp_path / "data"


def test_all_paths_are_absolute(tmp_path: Path):
    paths = PathsConfig.from_project_root(tmp_path)
    for name, value in paths.model_dump().items():
        if isinstance(value, Path):
            assert value.is_absolute(), f"{name} must be absolute; got {value}"


def test_string_accepted_at_construction(tmp_path: Path):
    paths = PathsConfig.from_project_root(str(tmp_path))
    assert isinstance(paths.project_root, Path)


def test_missing_required_root_raises():
    with pytest.raises(ValidationError):
        PathsConfig()  # project_root is required


def test_platformdirs_factory(monkeypatch):
    """Optional factory for pip-installed usage; uses platformdirs if available."""
    pytest.importorskip("platformdirs")
    paths = PathsConfig.from_platformdirs("echolon-test")
    assert paths.project_root.is_absolute()
    assert "echolon-test" in str(paths.project_root)


def test_unknown_override_rejected(tmp_path: Path):
    """Typo'd override keys must raise ValidationError, not be silently dropped."""
    with pytest.raises(ValidationError):
        PathsConfig.from_project_root(tmp_path, markte_data_dir=tmp_path / "x")


def test_relative_override_resolved(tmp_path: Path, monkeypatch):
    """Relative-path overrides are absolutised (against cwd, per Pydantic's semantics)."""
    monkeypatch.chdir(tmp_path)
    paths = PathsConfig.from_project_root(tmp_path, market_data_dir="rel/md")
    assert paths.market_data_dir.is_absolute()
    assert paths.market_data_dir == (tmp_path / "rel" / "md").resolve()


def test_string_override_coerced_to_path(tmp_path: Path):
    """String overrides are coerced to Path by Pydantic's native type handling."""
    paths = PathsConfig.from_project_root(tmp_path, market_data_dir=str(tmp_path / "x"))
    assert isinstance(paths.market_data_dir, Path)
    assert paths.market_data_dir == tmp_path / "x"
