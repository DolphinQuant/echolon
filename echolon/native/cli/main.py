"""Echolon CLI — `echolon <command>` entry point."""

import typer

from echolon.native.cli import examples as examples_cmd
from echolon.native.cli import init as init_cmd
from echolon.native.cli import schema as schema_cmd
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
app.command(name="init-strategy")(init_cmd.init_strategy_command)
app.command(name="schema")(schema_cmd.schema_command)
app.add_typer(examples_cmd.examples_app, name="examples")


if __name__ == "__main__":
    app()
