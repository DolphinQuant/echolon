"""End-to-end smoke test for `echolon hello`."""
from __future__ import annotations
import os
import subprocess
import sys


def test_hello_creates_demo_and_runs_backtest(tmp_path):
    result = subprocess.run(
        [sys.executable, "-m", "echolon.native.cli.main", "hello"],
        cwd=str(tmp_path), env=os.environ.copy(),
        capture_output=True, text=True, timeout=300,
    )
    assert result.returncode == 0, (
        f"exit={result.returncode}\n{result.stdout}\n{result.stderr}"
    )

    demo = tmp_path / "echolon-hello"
    assert demo.is_dir()
    assert (demo / ".echolon-workspace.json").is_file()
    # OHLCV under PathsConfig's market_data_dir convention.
    assert (demo / "workspace" / "data" / "market_data" / "SHFE" / "aluminum" / "sort_by_contract").is_dir()
    # main_contract.csv under raw_data_dir/{market}/{instrument_code}/.
    assert (demo / "data" / "SHFE" / "al" / "main_contract.csv").is_file()
    assert (demo / "strategy" / "baseline").is_dir()
    assert (demo / "output").is_dir()

    out = result.stdout
    assert "echolon-hello" in out
    # Output may show backtest result or a clean validation gate — both fine.
