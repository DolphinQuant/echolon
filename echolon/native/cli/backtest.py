"""`echolon backtest <strategy_dir>` — single-strategy backtest with workspace recovery.

Walks up from <strategy_dir> to find .echolon-workspace.json, recovers
the trading context (market, instrument, frequency, bar_size,
date_range, initial_capital), and runs the backtest. No CLI flags
required for the common case; flags override individual marker fields.

Distinct from `echolon backtest portfolio` (which is a sub-Typer at
echolon/backtest/cli.py for multi-slot portfolio runs).
"""
from __future__ import annotations
import json
import os
import sys
from pathlib import Path
from typing import Optional

import typer

from echolon.native.workspace import find_workspace_root, read_marker, WorkspaceNotFoundError
from echolon.native.validation import validate_indicator_names, validate_strategy_dir


def _run_backtest(
    strategy_dir: Path,
    *,
    instrument: Optional[str] = None,
    start: Optional[str] = None,
    end: Optional[str] = None,
    market: Optional[str] = None,
    frequency: Optional[str] = None,
    bar_size: Optional[str] = None,
    unsafe: bool = False,
    json_output: bool = False,
) -> None:
    """Plain Python helper — same body as ``backtest_single`` but without
    typer ``OptionInfo`` defaults so it's callable from other CLI commands
    (e.g. ``hello``)."""
    # Recover ctx from marker if available.
    ws_root: Optional[Path] = None
    try:
        ws_root = find_workspace_root(strategy_dir)
        marker = read_marker(ws_root)
        if not json_output:
            typer.echo(f"[ECHOLON] Workspace: {ws_root}")
    except WorkspaceNotFoundError:
        marker = {}
        if not json_output:
            typer.echo(
                "[ECHOLON] No workspace marker found; using CLI flags only. "
                "Tip: run `echolon init` to set up a workspace.",
                err=True,
            )

    market = market or marker.get("market")
    # Prefer the FULL instrument name ('aluminum') over the short code ('al') —
    # the indicator processor + data loader use the full name in path layout
    # under {indicators_backtest_dir}/{instrument}/. The short code is only
    # used for raw_data_dir/{market}/{instrument_code}/main_contract.csv.
    instrument = instrument or marker.get("instrument") or marker.get("instrument_code")
    start = start or (marker.get("date_range") or [None, None])[0]
    end = end or (marker.get("date_range") or [None, None])[1]
    frequency = frequency or marker.get("frequency", "interday")
    bar_size = bar_size or marker.get("bar_size", "1d")

    missing = [n for n, v in [("market", market), ("instrument", instrument),
                              ("start", start), ("end", end)] if v is None]
    if missing:
        typer.echo(
            f"Missing context fields: {missing}. Either run from a workspace "
            f"(produced by `echolon init`) or pass the flags explicitly.",
            err=True,
        )
        raise typer.Exit(2)

    if not unsafe:
        errors = []
        errors.extend(validate_strategy_dir(strategy_dir))
        errors.extend(validate_indicator_names(strategy_dir))
        if errors:
            if not json_output:
                typer.echo(f"Validation failed with {len(errors)} error(s):")
                for e in errors:
                    typer.echo(str(e))
            else:
                import json as _json
                _json.dump({
                    "ok": False,
                    "validation_errors": [str(e) for e in errors],
                }, sys.stdout, indent=2)
                sys.stdout.write("\n")
            raise typer.Exit(1)
        if not json_output:
            typer.echo("✓ Validation passed.")

    # Thread workspace as ECHOLON_PROJECT_ROOT so PathsConfig.from_env() resolves
    # all defaults (raw_data_dir, market_data_dir, indicators_backtest_dir, etc.)
    # relative to the workspace.
    if ws_root is not None:
        os.environ["ECHOLON_PROJECT_ROOT"] = str(ws_root)

    from echolon.config.paths_config import PathsConfig
    from echolon import quick_start
    from echolon.backtest.engine.backtest_runner import BacktestRunner
    from echolon.indicators.run import run_indicator_calculation
    from echolon.strategy.loader import StrategyLoader

    paths = PathsConfig.from_env()

    qs = quick_start(
        market=market, instrument=instrument,
        start_date=start, end_date=end,
        frequency=frequency, bar_size=bar_size,
    )
    ctx = qs[0]
    bt_cfg = qs[1]
    # Pin paths explicitly to PathsConfig so they don't depend on cwd or
    # quick_start's defaults.
    bt_cfg.strategy_dir = strategy_dir.resolve()
    bt_cfg.indicator_dir = paths.indicators_backtest_dir
    bt_cfg.market_data_dir = paths.market_data_dir

    # `strategy_code_dir` triggers slot-style indicator layout:
    # {indicators_backtest_dir}/{slot_name}/{strategy_indicators.csv,by_contract/}
    # where slot_name = Path(strategy_code_dir).name (e.g. "baseline").
    slot_name = strategy_dir.name
    slot_indicator_dir = paths.indicators_backtest_dir / slot_name

    # Compute indicators if missing.
    indicators_csv = slot_indicator_dir / "strategy_indicators.csv"
    if not indicators_csv.exists():
        if not json_output:
            typer.echo(f"[ECHOLON] Computing indicators (first run for this workspace)…")
        ind_list_path = strategy_dir / "strategy_indicator_list.json"
        if not ind_list_path.is_file():
            cands = list(strategy_dir.glob("*indicator*list*.json"))
            if not cands:
                typer.echo(
                    f"No strategy_indicator_list.json under {strategy_dir}.",
                    err=True,
                )
                raise typer.Exit(2)
            ind_list_path = cands[0]
        indicator_list = json.loads(ind_list_path.read_text())
        run_indicator_calculation(
            ctx=ctx,
            output_dir=str(slot_indicator_dir),
            indicator_list=indicator_list,
            use_parallel=False,
            start_date=start,
            end_date=end,
            paths=paths,
        )

    if not json_output:
        typer.echo(f"[ECHOLON] Running backtest: {strategy_dir.name} ({instrument} {start}..{end})")

    runner = BacktestRunner(
        ctx=ctx,
        strategy_code_dir=str(strategy_dir.resolve()),
        backtest_config=bt_cfg,
    )
    runner.load_data()
    loader = StrategyLoader(strategy_dir.resolve())
    default_params = loader.load_attr("strategy_params", "DEFAULT_PARAMS")
    try:
        result = runner.run(default_params, context='debug')
    except Exception as exc:
        # Emit informative output on backtest failure. In --json mode, this is
        # what an LLM agent reads to decide whether to retry / change params.
        if json_output:
            import json as _json
            _json.dump({
                "ok": False,
                "error": f"{type(exc).__name__}: {exc}",
                "strategy_dir": str(strategy_dir.resolve()),
                "context": {
                    "market": market, "instrument": instrument,
                    "start": start, "end": end,
                    "frequency": frequency, "bar_size": bar_size,
                },
            }, sys.stdout, indent=2)
            sys.stdout.write("\n")
            raise typer.Exit(1)
        # In human-readable mode, re-raise so the user sees the stack trace.
        # (Hello catches this; standalone `echolon backtest` lets it propagate.)
        raise

    metrics = (result or {}).get("performance_metrics", {}) if isinstance(result, dict) else {}
    if json_output:
        import json as _json
        _json.dump({
            "ok": True,
            "sharpe": metrics.get("sharpe_ratio"),
            "max_drawdown": metrics.get("max_drawdown"),
            "annual_return": metrics.get("annual_return"),
            "win_rate": metrics.get("win_rate"),
            "total_trades": metrics.get("total_trades"),
            "profit_factor": metrics.get("profit_factor"),
            "trades_per_week": metrics.get("trades_per_week"),
            "strategy_dir": str(strategy_dir.resolve()),
            "context": {
                "market": market, "instrument": instrument,
                "start": start, "end": end,
                "frequency": frequency, "bar_size": bar_size,
            },
        }, sys.stdout, indent=2)
        sys.stdout.write("\n")
    else:
        sharpe = metrics.get("sharpe_ratio")
        max_dd = metrics.get("max_drawdown")
        n_trades = metrics.get("total_trades", 0)
        sharpe_str = f"{sharpe:.2f}" if isinstance(sharpe, (int, float)) else str(sharpe)
        max_dd_str = f"{max_dd*100:.1f}%" if isinstance(max_dd, (int, float)) else str(max_dd)
        typer.echo(
            f"[ECHOLON] ✓ Sharpe: {sharpe_str} | MaxDD: {max_dd_str} | {n_trades} trades"
        )


def backtest_single(
    strategy_dir: Path = typer.Argument(..., help="Strategy directory (under a workspace with .echolon-workspace.json)"),
    instrument: Optional[str] = typer.Option(None, "--instrument", help="Override workspace marker's instrument"),
    start: Optional[str] = typer.Option(None, "--start", help="Override marker start date"),
    end: Optional[str] = typer.Option(None, "--end", help="Override marker end date"),
    market: Optional[str] = typer.Option(None, "--market", help="Override marker market"),
    frequency: Optional[str] = typer.Option(None, "--frequency"),
    bar_size: Optional[str] = typer.Option(None, "--bar-size"),
    unsafe: bool = typer.Option(False, "--unsafe", help="Skip pre-validation"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON metrics (for LLM agents)"),
) -> None:
    """Run a backtest, recovering ctx from the workspace marker file.

    Output mode:
    - default: human-readable progress + summary line.
    - --json: a single JSON object on stdout with keys
      ``{sharpe, max_drawdown, total_trades, annual_return, win_rate, ...}``.
    """
    _run_backtest(
        strategy_dir=strategy_dir,
        instrument=instrument, start=start, end=end, market=market,
        frequency=frequency, bar_size=bar_size,
        unsafe=unsafe, json_output=json_output,
    )
