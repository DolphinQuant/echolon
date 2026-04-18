"""Tests for `echolon deploy` CLI sub-app."""
from typer.testing import CliRunner

from echolon.native.cli.main import app

runner = CliRunner()


def test_deploy_help_shows_subcommands():
    """`echolon deploy --help` should list all three deploy subcommands."""
    result = runner.invoke(app, ["deploy", "--help"])
    assert result.exit_code == 0
    assert "single" in result.stdout
    assert "portfolio" in result.stdout
    assert "portfolio-cycle" in result.stdout
