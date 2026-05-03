"""`echolon hello` — out-of-the-box demo.

Internally: copy bundled SHFE aluminum sample → copy minimal template →
write workspace marker → run backtest. No network. ~30 seconds.

Distinct from `echolon init` only in the data source: hello uses the
bundled wheel sample; init downloads via akshare.
"""
from __future__ import annotations
import os
import shutil
from pathlib import Path

import typer

from echolon.data.sample import copy_sample_to, get_sample_manifest
from echolon.native.templates import template_path
from echolon.native.workspace import write_marker

DEMO_DIR_NAME = "echolon-hello"


def hello_command(
    bundle: str = typer.Option("shfe_al", "--bundle", help="Sample bundle name"),
    template: str = typer.Option("momentum_breakout", "--template",
                                  help="Template to scaffold under strategy/baseline/. "
                                       "Default 'momentum_breakout' produces actual trades on the demo data; "
                                       "'minimal' is hold-forever (educational, no trades)."),
    force: bool = typer.Option(False, "--force", help="Overwrite existing ./echolon-hello/"),
) -> None:
    """Bundled-data instant demo. Lays a workspace, scaffolds a strategy,
    runs a backtest."""

    # Pre-flight ta-lib (the indicator pipeline imports talib). If missing,
    # surface the friendly install hint upfront instead of failing mid-run.
    try:
        import talib  # noqa: F401
    except ImportError:
        from echolon.native.cli.doctor import _check_talib
        check = _check_talib()
        typer.echo(f"[ECHOLON] {check['detail']}", err=True)
        if check.get("hint"):
            for line in check["hint"].splitlines():
                typer.echo(f"[ECHOLON]   {line}", err=True)
        raise typer.Exit(3)

    cwd = Path.cwd().resolve()
    home = Path(os.environ.get("HOME", str(Path.home()))).resolve()
    if cwd == home:
        typer.echo("Refusing to create demo at $HOME. cd into a project dir first.", err=True)
        raise typer.Exit(2)
    if cwd == Path("/"):
        typer.echo("Refusing to create demo at /.", err=True)
        raise typer.Exit(2)

    demo = cwd / DEMO_DIR_NAME
    if demo.exists():
        if not force:
            typer.echo(
                f"./{DEMO_DIR_NAME}/ already exists. Pass --force to overwrite.",
                err=True,
            )
            raise typer.Exit(2)
        shutil.rmtree(demo)
    demo.mkdir(parents=True, exist_ok=False)
    typer.echo(f"[ECHOLON] Creating demo workspace at ./{demo.name}/")

    # 1. Copy bundled sample. copy_sample_to writes to PathsConfig's canonical layout:
    #   demo/data/{market}/{instrument_code}/main_contract.csv
    #   demo/workspace/data/market_data/{market}/{instrument}/sort_by_contract/...
    manifest = get_sample_manifest(bundle)
    copy_sample_to(bundle, demo)
    typer.echo(
        f"[ECHOLON]   data + workspace/data/market_data populated  "
        f"({len(manifest['contracts'])} contracts, "
        f"{manifest['date_range'][0]}–{manifest['date_range'][1]})"
    )

    # 2. Scaffold template into strategy/baseline/.
    strategy_root = demo / "strategy" / "baseline"
    strategy_root.mkdir(parents=True, exist_ok=True)
    shutil.copytree(template_path(template), strategy_root, dirs_exist_ok=True)
    typer.echo(f"[ECHOLON]   strategy/baseline/  ({template} template)")

    # 3. Empty output dir.
    (demo / "output").mkdir(parents=True, exist_ok=True)

    # 4. Workspace marker.
    write_marker(
        demo,
        market=manifest["market"], instrument=manifest["instrument"],
        instrument_code=manifest["instrument_code"],
        frequency=manifest["frequency"], bar_size=manifest["bar_size"],
        date_range=tuple(manifest["date_range"]),
        data_source="bundled", initial_capital=200000.0,
    )
    typer.echo(f"[ECHOLON]   .echolon-workspace.json")

    # 5. Set ECHOLON_PROJECT_ROOT so all subsequent pipeline calls resolve
    #    paths relative to the demo workspace.
    os.environ["ECHOLON_PROJECT_ROOT"] = str(demo)

    # 6. Run backtest immediately so the user sees a number.
    typer.echo(f"[ECHOLON] Running backtest...")
    from echolon.native.cli.backtest import _run_backtest
    try:
        _run_backtest(strategy_dir=strategy_root)
    except typer.Exit as e:
        if e.exit_code != 0:
            typer.echo(f"[ECHOLON] (Backtest exited {e.exit_code} — see output above.)")
    except Exception as exc:
        # The bundled sample is small; some templates (or short windows) may
        # produce zero trades and raise BT-002. The DEMO completed successfully
        # — the user saw the pipeline end-to-end. Surface the message and continue.
        typer.echo(f"[ECHOLON] Backtest raised: {type(exc).__name__}: {exc}")
        typer.echo(f"[ECHOLON] (Pipeline completed; the bundled sample window or "
                   f"chosen template may not produce trades. Try editing "
                   f"./{demo.name}/strategy/baseline/entry.py.)")

    typer.echo("")
    typer.echo(f"[ECHOLON] Try editing ./{demo.name}/strategy/baseline/entry.py and re-running:")
    typer.echo(f"[ECHOLON]   echolon backtest single ./{demo.name}/strategy/baseline/")
