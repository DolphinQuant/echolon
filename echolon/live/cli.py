"""`echolon deploy` CLI sub-app."""
import typer

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
    raise typer.Exit(code=1)  # filled in Task 2


@deploy_app.command("portfolio")
def deploy_portfolio(
    config: str = typer.Option(..., "--config", "-c", help="Path to portfolio_deploy_config.json"),
    validate_only: bool = typer.Option(False, "--validate-only", help="Validate schema + paths then exit"),
) -> None:
    """Run multi-slot portfolio live trading (scheduled continuous)."""
    raise typer.Exit(code=1)  # filled in Task 3


@deploy_app.command("portfolio-cycle")
def deploy_portfolio_cycle(
    config: str = typer.Option(..., "--config", "-c", help="Path to portfolio_deploy_config.json"),
) -> None:
    """Run a single portfolio trading cycle (for testing)."""
    raise typer.Exit(code=1)  # filled in Task 3
