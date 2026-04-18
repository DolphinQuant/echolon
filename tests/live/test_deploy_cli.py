"""Tests for `echolon deploy` CLI sub-app."""
from unittest.mock import MagicMock, patch

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


def test_deploy_single_invokes_trading_runner(tmp_path):
    """`echolon deploy single --config X` should load DeployConfig, build ctx, and run TradingRunner."""
    cfg = tmp_path / "deploy_config.json"
    cfg.write_text(
        '{"use_test_account": true, "market": "SHFE", "instrument": "al",'
        ' "frequency": "interday", "bar_size": "1d", "initial_capital": 100000.0}'
    )

    with patch("echolon.live.cli.TradingRunner") as MockRunner, \
         patch("echolon.live.cli.MarketFactory") as MockFactory:
        mock_ctx = MagicMock()
        mock_ctx.market_code = "SHFE"
        mock_ctx.instrument_name = "al"
        MockFactory.create.return_value = mock_ctx
        runner_instance = MagicMock()
        MockRunner.return_value = runner_instance

        result = runner.invoke(app, ["deploy", "single", "--config", str(cfg)])

        assert result.exit_code == 0, result.stdout
        MockFactory.create.assert_called_once_with(
            market="SHFE", instrument="al", frequency="interday", bar_size="1d",
        )
        runner_instance.run.assert_called_once()
        runner_instance.stop.assert_called_once()
