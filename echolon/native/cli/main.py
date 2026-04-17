"""Echolon CLI — `echolon <command>` entry point."""

import typer

from echolon.native.cli import validate as validate_cmd

app = typer.Typer(
    name="echolon",
    help="Echolon — See what others can't.",
    no_args_is_help=True,
)


@app.callback()
def _callback() -> None:
    """Echolon CLI — multi-command entry point."""


app.command(name="validate")(validate_cmd.validate_command)


if __name__ == "__main__":
    app()
