"""Tests for `echolon run` CLI."""

from pathlib import Path

from typer.testing import CliRunner

from echolon.native.cli.main import app


runner = CliRunner()


def _make_invalid_strategy(tmp_path: Path) -> Path:
    (tmp_path / "strategy.py").write_text("")
    return tmp_path


def test_run_fails_on_validation_errors(tmp_path):
    _make_invalid_strategy(tmp_path)
    result = runner.invoke(app, ["run", str(tmp_path),
                                 "--instrument", "cu",
                                 "--start", "2020-01-01",
                                 "--end", "2023-12-31"])
    assert result.exit_code != 0


def test_run_with_unsafe_shows_warning(tmp_path):
    _make_invalid_strategy(tmp_path)
    result = runner.invoke(app, ["run", str(tmp_path),
                                 "--instrument", "cu",
                                 "--start", "2020-01-01",
                                 "--end", "2023-12-31",
                                 "--unsafe"])
    assert "unsafe" in result.stdout.lower()


def test_run_help():
    result = runner.invoke(app, ["run", "--help"])
    assert result.exit_code == 0
    assert "--unsafe" in result.stdout
    assert "--instrument" in result.stdout
