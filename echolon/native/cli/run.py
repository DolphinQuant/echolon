"""`echolon run <dir>` — run backtest on a strategy directory."""

from pathlib import Path

import typer

from echolon.native.validation import (
    validate_indicator_names,
    validate_strategy_dir,
)


def run_command(
    strategy_dir: Path = typer.Argument(..., help="Strategy directory"),
    instrument: str = typer.Option(..., "--instrument", help="Market instrument code"),
    start: str = typer.Option(..., "--start", help="Backtest start (YYYY-MM-DD)"),
    end: str = typer.Option(..., "--end", help="Backtest end (YYYY-MM-DD)"),
    market: str = typer.Option("shfe", "--market", help="Market code"),
    frequency: str = typer.Option("interday", "--frequency"),
    bar_size: str = typer.Option("1d", "--bar-size"),
    unsafe: bool = typer.Option(False, "--unsafe", help="Skip validation. Not recommended."),
) -> None:
    """Run a backtest on a strategy directory. Validates first unless --unsafe."""
    if unsafe:
        typer.echo("⚠️  Running with --unsafe. Validation disabled.")
    else:
        errors = []
        errors.extend(validate_strategy_dir(strategy_dir))
        errors.extend(validate_indicator_names(strategy_dir))
        if errors:
            typer.echo(f"Validation failed with {len(errors)} error(s):")
            for err in errors:
                typer.echo(str(err))
            typer.echo("\nFix errors and re-run, or pass --unsafe to bypass (not recommended).")
            raise typer.Exit(code=1)
        typer.echo("✓ Validation passed.")

    try:
        from echolon import quick_start
        from echolon.backtest.engine.backtest_runner import BacktestRunner
    except Exception as e:
        typer.echo(f"Backtest subsystem not available: {e}")
        raise typer.Exit(code=3)

    ctx, bt, opt = quick_start(
        market=market, instrument=instrument,
        start_date=start, end_date=end,
        frequency=frequency, bar_size=bar_size,
    )
    bt.strategy_dir = strategy_dir.resolve()

    typer.echo(f"Running backtest: {instrument} {start}..{end}")
    runner = BacktestRunner(ctx=ctx, backtest_config=bt, optuna_config=opt)
    result = runner.run() if hasattr(runner, "run") else None
    typer.echo(f"✓ Backtest complete. Result: {result}")
