"""Both deploy configs expose a trading_calendar_path field."""
import json

from echolon.live.config.deploy_config import DeployConfig
from echolon.live.config.portfolio_deploy_config import PortfolioDeployConfig


def test_deploy_config_has_trading_calendar_path(tmp_path):
    cfg = tmp_path / "deploy_config.json"
    cfg.write_text(json.dumps({
        "market": "SHFE", "instrument": "al", "frequency": "interday",
        "bar_size": "1d", "initial_capital": 100000.0,
        "trading_calendar_path": "./session/trading_calendar.csv",
    }))
    c = DeployConfig.load(str(cfg))
    assert c.trading_calendar_path.endswith("trading_calendar.csv")


def test_portfolio_deploy_config_has_trading_calendar_path(tmp_path):
    cfg = tmp_path / "portfolio_deploy_config.json"
    cfg.write_text(json.dumps({
        "slots": [], "schedule": {}, "account": {},
        "deploy": {"trading_calendar_path": "./session/trading_calendar.csv"},
    }))
    c = PortfolioDeployConfig.load(str(cfg))
    assert c.deploy.trading_calendar_path.endswith("trading_calendar.csv")


def test_missing_field_defaults_to_empty_string():
    """Back-compat: older configs without the field still load."""
    # (construct bare instance; verify default)
    c = DeployConfig()
    assert c.trading_calendar_path == ""
