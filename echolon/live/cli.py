"""`echolon deploy` CLI sub-app."""
import logging

import typer

from echolon.config.markets.factory import MarketFactory
from echolon.live.config.deploy_config import DeployConfig
from echolon.live.config.portfolio_deploy_config import PortfolioDeployConfig
from echolon.live.portfolio_runner import PortfolioTradingRunner
from echolon.live.runner import TradingRunner

logger = logging.getLogger(__name__)

deploy_app = typer.Typer(
    name="deploy",
    help="Run live trading — single-instrument or portfolio.",
    no_args_is_help=True,
)


@deploy_app.command("single")
def deploy_single(
    config: str = typer.Option(..., "--config", "-c", help="Path to deploy_config.json"),
) -> None:
    """Run single-instrument continuous live trading."""
    deploy_config = DeployConfig.load(config)
    ctx = MarketFactory.create(
        market=deploy_config.market,
        instrument=deploy_config.instrument,
        frequency=deploy_config.frequency,
        bar_size=deploy_config.bar_size,
    )

    logger.info(
        "Starting deploy: market=%s instrument=%s test_mode=%s",
        ctx.market_code, ctx.instrument_name, deploy_config.use_test_account,
    )

    trading_runner = TradingRunner(config=deploy_config, ctx=ctx)
    try:
        trading_runner.run()
    except KeyboardInterrupt:
        logger.info("Deploy stopped by user")
    finally:
        trading_runner.stop()


@deploy_app.command("portfolio")
def deploy_portfolio(
    config: str = typer.Option(..., "--config", "-c", help="Path to portfolio_deploy_config.json"),
    validate_only: bool = typer.Option(False, "--validate-only", help="Validate schema + paths then exit"),
) -> None:
    """Run multi-slot portfolio live trading (scheduled continuous)."""
    portfolio_config = PortfolioDeployConfig.load(config)
    enabled = portfolio_config.get_enabled_slots()
    logger.info("Loaded portfolio config: %d enabled slots", len(enabled))

    if validate_only:
        logger.info("Validation complete — exiting (--validate-only)")
        return

    portfolio_runner = PortfolioTradingRunner(config=portfolio_config)
    try:
        portfolio_runner.run()
    except KeyboardInterrupt:
        logger.info("Portfolio deploy stopped by user")
    finally:
        portfolio_runner.stop()


@deploy_app.command("portfolio-cycle")
def deploy_portfolio_cycle(
    config: str = typer.Option(..., "--config", "-c", help="Path to portfolio_deploy_config.json"),
) -> None:
    """Run a single portfolio trading cycle (for testing)."""
    portfolio_config = PortfolioDeployConfig.load(config)
    portfolio_runner = PortfolioTradingRunner(config=portfolio_config)
    try:
        result = portfolio_runner.run_single_cycle()
        logger.info("Single portfolio cycle complete: status=%s", result.get("status"))
    finally:
        portfolio_runner.stop()
