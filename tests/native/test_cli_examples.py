"""Tests for `echolon examples` CLI."""

from pathlib import Path

from typer.testing import CliRunner

from echolon.native.cli.main import app


runner = CliRunner()


def test_examples_list():
    result = runner.invoke(app, ["examples", "--list"])
    assert result.exit_code == 0
    assert "01_minimal" in result.stdout
    assert "02_momentum_breakout" in result.stdout


def test_examples_copy(tmp_path):
    dest = tmp_path / "my_copy"
    result = runner.invoke(app, ["examples", "copy", "01_minimal", str(dest)])
    assert result.exit_code == 0
    assert dest.is_dir()
    assert (dest / "strategy.py").exists()


def test_examples_copy_unknown_fails(tmp_path):
    result = runner.invoke(app, ["examples", "copy", "bogus", str(tmp_path / "x")])
    assert result.exit_code != 0
