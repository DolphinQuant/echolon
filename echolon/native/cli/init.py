"""`echolon init-strategy <dir> --template <t>` — scaffold new strategy."""

import shutil
from pathlib import Path

import typer

from echolon.native.templates import AVAILABLE_TEMPLATES, template_path


def init_strategy_command(
    target_dir: Path = typer.Argument(..., help="Where to create the new strategy"),
    template: str = typer.Option("minimal", "--template", "-t",
                                  help=f"Template name. Available: {AVAILABLE_TEMPLATES}"),
) -> None:
    """Scaffold a new strategy directory from a bundled template."""
    if template not in AVAILABLE_TEMPLATES:
        typer.echo(f"Unknown template: {template}")
        typer.echo(f"Available: {', '.join(AVAILABLE_TEMPLATES)}")
        raise typer.Exit(code=2)

    if target_dir.exists() and any(target_dir.iterdir()):
        typer.echo(f"Target directory already exists and is not empty: {target_dir}")
        raise typer.Exit(code=2)

    src = template_path(template)
    shutil.copytree(src, target_dir, dirs_exist_ok=True)

    typer.echo(f"✓ Created strategy at {target_dir}")
    typer.echo("✓ Next steps:")
    typer.echo(f"   1. cd {target_dir}")
    typer.echo("   2. Edit entry.py / exit.py / sizer.py to customize")
    typer.echo(f"   3. echolon validate {target_dir}")
    typer.echo(f"   4. echolon run {target_dir} --instrument cu --start 2020-01-01 --end 2023-12-31")
