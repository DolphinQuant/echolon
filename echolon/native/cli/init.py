"""`echolon init <dir>` — scaffold a strategy, with optional full-workspace setup.

Two modes, distinguished by whether market/data flags are provided:

1. Template-only (legacy `init-strategy` semantics):
       echolon init my-strategy --template minimal
   Just copies a bundled template into the target dir. Same as
   `echolon examples copy <template> <dir>`.

2. Full workspace (new):
       echolon init my-zinc --market SHFE --instrument zinc \\
                            --start 2022-01-01 --end 2024-12-31 \\
                            --template minimal
   Creates a workspace with downloaded data (via akshare),
   main_contract.csv (derived from akshare's continuous-main series),
   a scaffolded strategy under workspace/strategy/baseline/, and a
   .echolon-workspace.json marker for `echolon backtest` to find later.
"""
from __future__ import annotations
import os
import shutil
from pathlib import Path
from typing import Optional

import typer

from echolon.native.templates import AVAILABLE_TEMPLATES, template_path
from echolon.native.workspace import write_marker


def init_command(
    target: Path = typer.Argument(..., help="Target directory (workspace or strategy)"),
    template: str = typer.Option("minimal", "--template", "-t",
                                  help=f"Strategy template. Available: {AVAILABLE_TEMPLATES}"),
    # Full-init flags (all optional — when absent, runs in template-only mode).
    market: Optional[str] = typer.Option(None, "--market", help="Market (e.g. SHFE)"),
    instrument: Optional[str] = typer.Option(None, "--instrument", help="Instrument name (e.g. aluminum, zinc)"),
    start: Optional[str] = typer.Option(None, "--start", help="Start date YYYY-MM-DD"),
    end: Optional[str] = typer.Option(None, "--end", help="End date YYYY-MM-DD"),
    initial_capital: float = typer.Option(200000.0, "--initial-capital"),
    force: bool = typer.Option(False, "--force", help="Overwrite existing target"),
) -> None:
    """Scaffold a strategy. With --market/--instrument/--start/--end, also
    create a full workspace with downloaded data."""

    if template not in AVAILABLE_TEMPLATES:
        typer.echo(f"Unknown template: {template}; available: {AVAILABLE_TEMPLATES}", err=True)
        raise typer.Exit(2)

    full_init_flags = [market, instrument, start, end]
    n_full_flags = sum(1 for f in full_init_flags if f is not None)
    if n_full_flags not in (0, 4):
        typer.echo(
            "Full-init requires all of --market / --instrument / --start / --end "
            "or none of them.", err=True,
        )
        raise typer.Exit(2)

    is_full_init = n_full_flags == 4

    # Pre-flight ta-lib for full-init (indicator pipeline imports talib).
    if is_full_init:
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

    # Safety guards (full-init only — legacy template-only mode preserves old behavior).
    if is_full_init:
        cwd = Path.cwd().resolve()
        home = Path(os.environ.get("HOME", str(Path.home()))).resolve()
        if cwd == home:
            typer.echo("Refusing to create a workspace at $HOME. cd into a project dir.", err=True)
            raise typer.Exit(2)
        if cwd == Path("/"):
            typer.echo("Refusing to create a workspace at /.", err=True)
            raise typer.Exit(2)

    target = target.resolve()
    if target.exists():
        if not force:
            typer.echo(f"{target} already exists. Pass --force to overwrite.", err=True)
            raise typer.Exit(2)
        shutil.rmtree(target)

    if not is_full_init:
        # Template-only mode (legacy init-strategy).
        target.mkdir(parents=True, exist_ok=False)
        shutil.copytree(template_path(template), target, dirs_exist_ok=True)
        typer.echo(f"✓ Scaffolded {template} → {target}")
        typer.echo("Next: edit entry.py / exit.py / sizer.py and run `echolon validate <dir>` + `echolon backtest <dir>`.")
        return

    # Full-init mode.
    target.mkdir(parents=True, exist_ok=False)
    typer.echo(f"[ECHOLON] Creating workspace at {target}")

    from echolon.config.markets.factory import MarketFactory
    spec = MarketFactory.get_instrument_flexible(market, instrument)
    if spec is None:
        typer.echo(
            f"Unknown {market} instrument {instrument!r}. "
            f"Supported: {MarketFactory.list_instruments(market)}",
            err=True,
        )
        raise typer.Exit(2)
    instrument_code = spec.code

    # Test stub — bypass akshare entirely.
    test_stub = os.environ.get("ECHOLON_INIT_TEST_STUB") == "1"

    raw_root = target / "data" / "raw" / market

    if test_stub:
        typer.echo("[ECHOLON]   (test stub — skipping akshare)")
        _write_stub_data(raw_root, instrument, instrument_code)
    elif market.upper() == "SHFE":
        # Friendly upfront check: if akshare isn't installed, tell the user
        # how to fix it INSTEAD of crashing with ModuleNotFoundError 30 lines deep.
        try:
            import akshare  # noqa: F401
        except ImportError:
            typer.echo(
                "[ECHOLON] akshare is not installed.\n"
                "[ECHOLON] `echolon init` needs it to download SHFE data.\n"
                "[ECHOLON]\n"
                "[ECHOLON] Install with:\n"
                "[ECHOLON]   pip install echolon[shfe]\n",
                err=True,
            )
            raise typer.Exit(3)

        _full_init_shfe(
            raw_root=raw_root, instrument=instrument, instrument_code=instrument_code,
            start=start, end=end,
        )
    else:
        typer.echo(
            f"--market {market} not yet wired into `echolon init` (v1 covers SHFE only).\n"
            f"Want another market? See echolon's BaseExtractor and consider opening an issue.",
            err=True,
        )
        raise typer.Exit(2)

    # Scaffold strategy from template into workspace/strategy/baseline/.
    strategy_root = target / "strategy" / "baseline"
    strategy_root.mkdir(parents=True, exist_ok=True)
    shutil.copytree(template_path(template), strategy_root, dirs_exist_ok=True)
    typer.echo(f"[ECHOLON]   strategy/baseline/ ({template} template — fill in the logic)")

    # Empty output dir.
    (target / "output").mkdir(parents=True, exist_ok=True)

    # Workspace marker.
    write_marker(
        target,
        market=market, instrument=instrument, instrument_code=instrument_code,
        frequency="interday", bar_size="1d",
        date_range=(start, end),
        data_source=("test_stub" if test_stub else "akshare"),
        initial_capital=initial_capital,
    )

    typer.echo("")
    typer.echo("[ECHOLON] Next:")
    typer.echo(f"[ECHOLON]   1. Open {target.name}/ in your MCP-aware editor.")
    typer.echo(f"[ECHOLON]   2. Fill in the logic in {target.name}/strategy/baseline/.")
    typer.echo(f"[ECHOLON]      Or ask the LLM agent to do it via echolon-mcp's tools.")
    typer.echo(f"[ECHOLON]   3. Run: echolon backtest {target.name}/strategy/baseline/")


def _full_init_shfe(*, raw_root: Path, instrument: str, instrument_code: str,
                    start: str, end: str) -> None:
    """Real SHFE full-init: download via akshare, run standardizer, derive main_contract."""
    import pandas as pd

    typer.echo(f"[ECHOLON] Downloading {instrument_code} data via akshare...")
    from echolon.data.extractors.shfe.akshare_extractor import SHFEAkshareExtractor
    extractor = SHFEAkshareExtractor(market="SHFE", asset=instrument)
    raw_df = extractor.extract_raw(start_date=start, end_date=end, save=False)
    if raw_df.empty:
        typer.echo("No data returned by akshare for the requested range.", err=True)
        raise typer.Exit(3)

    instrument_dir = raw_root / instrument
    instrument_dir.mkdir(parents=True, exist_ok=True)
    contract_dir = instrument_dir / "sort_by_contract"
    contract_dir.mkdir(exist_ok=True)
    for contract, group in raw_df.groupby("contract"):
        group.to_csv(contract_dir / f"{contract}.csv", index=False)
    raw_df.sort_values("date").to_csv(instrument_dir / "sort_by_date.csv", index=False)
    pd.DataFrame({
        "date": sorted(raw_df["date"].unique()), "is_trading_day": True,
    }).to_csv(instrument_dir / "trading_calendar.csv", index=False)

    # Derive main_contract.csv via akshare's continuous-main series.
    typer.echo("[ECHOLON]   Building main_contract.csv from continuous-main series")
    main_dir = raw_root / instrument_code
    main_dir.mkdir(exist_ok=True)
    _derive_main_contract_csv(instrument_code, start, end, main_dir / "main_contract.csv")
    typer.echo(f"[ECHOLON]   data/raw/{raw_root.name}/{instrument}/  ({len(raw_df['contract'].unique())} contracts)")


def _derive_main_contract_csv(instrument_code: str, start: str, end: str, out_path: Path) -> None:
    import akshare as ak
    import pandas as pd
    df = ak.futures_main_sina(symbol=f"{instrument_code.upper()}0")
    if df is None or df.empty:
        raise typer.Exit(3)
    df = df.copy()
    df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
    df = df[(df["date"] >= start) & (df["date"] <= end)]
    contract_col = next((c for c in ("symbol", "contract", "ts_code") if c in df.columns), None)
    if contract_col is None:
        typer.echo(f"akshare main series schema unrecognized: {list(df.columns)}", err=True)
        raise typer.Exit(3)
    out = df[["date", contract_col]].rename(columns={contract_col: "main_contract"})
    out["main_contract"] = out["main_contract"].apply(
        lambda c: c.lower() if c.lower().endswith(".sf") else f"{c.lower()}.SF"
    )
    out.to_csv(out_path, index=False)


def _write_stub_data(raw_root: Path, instrument: str, instrument_code: str) -> None:
    """Test-stub: skip akshare, write a few rows of synthetic data."""
    import pandas as pd
    instrument_dir = raw_root / instrument
    (instrument_dir / "sort_by_contract").mkdir(parents=True, exist_ok=True)
    stub = pd.DataFrame({
        "contract": ["al2401"] * 3,
        "date": ["2024-01-02", "2024-01-03", "2024-01-04"],
        "prev_close": [19000.0, 19030.0, 19060.0],
        "prev_settlement": [19000.0, 19030.0, 19060.0],
        "open": [19000.0, 19030.0, 19060.0],
        "high": [19050.0, 19080.0, 19110.0],
        "low":  [18990.0, 19000.0, 19020.0],
        "close": [19030.0, 19060.0, 19090.0],
        "settlement": [19030.0, 19060.0, 19090.0],
        "price_change": [0.0, 30.0, 30.0],
        "settlement_change": [0.0, 30.0, 30.0],
        "volume": [5000.0, 6000.0, 5500.0],
        "turnover": [95.15, 114.36, 105.0],
        "open_interest": [30000.0, 31000.0, 30500.0],
    })
    stub.to_csv(instrument_dir / "sort_by_contract" / "al2401.csv", index=False)
    stub.to_csv(instrument_dir / "sort_by_date.csv", index=False)
    pd.DataFrame({"date": ["2024-01-02"], "is_trading_day": True}).to_csv(
        instrument_dir / "trading_calendar.csv", index=False
    )
    main_dir = raw_root / instrument_code
    main_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame({
        "date": ["2024-01-02"], "main_contract": ["al2401.SF"],
    }).to_csv(main_dir / "main_contract.csv", index=False)


# Back-compat alias for `cli/main.py`'s existing `init-strategy` registration.
init_strategy_command = init_command
