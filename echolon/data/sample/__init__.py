"""Read-only accessors for sample datasets bundled inside the wheel."""
from __future__ import annotations
from importlib import resources
import json
from pathlib import Path
from typing import List


def list_sample_bundles() -> List[str]:
    pkg = resources.files("echolon.data.sample")
    return sorted(
        item.name for item in pkg.iterdir()
        if item.is_dir() and (item / "MANIFEST.json").is_file()
    )


def get_sample_manifest(bundle_name: str) -> dict:
    pkg = resources.files("echolon.data.sample") / bundle_name
    manifest = pkg / "MANIFEST.json"
    if not manifest.is_file():
        raise KeyError(
            f"Unknown sample bundle {bundle_name!r}. "
            f"Available: {list_sample_bundles()}"
        )
    return json.loads(manifest.read_text())


def copy_sample_to(bundle_name: str, project_root: Path) -> List[Path]:
    """Lay out the bundle following echolon's canonical PathsConfig layout
    relative to ``project_root``.

    Materializes:
      project_root/data/{market}/{instrument_code}/main_contract.csv
      project_root/workspace/data/market_data/{market}/{instrument}/sort_by_contract/{contract}.csv
      project_root/workspace/data/market_data/{market}/{instrument}/sort_by_date.csv
      project_root/workspace/data/market_data/{market}/{instrument}/trading_calendar.csv

    These match ``PathsConfig.from_project_root(project_root)`` so a caller
    that sets ``ECHOLON_PROJECT_ROOT={project_root}`` gets all paths
    resolved correctly via ``PathsConfig.from_env()``.
    """
    m = get_sample_manifest(bundle_name)
    instrument = m["instrument"]
    code = m["instrument_code"]
    market = m["market"]

    raw_root = project_root / "data" / market
    market_data_root = (project_root / "workspace" / "data"
                        / "market_data" / market / instrument)
    contract_dir = market_data_root / "sort_by_contract"

    contract_dir.mkdir(parents=True, exist_ok=True)
    main_root = raw_root / code
    main_root.mkdir(parents=True, exist_ok=True)

    pkg = resources.files("echolon.data.sample") / bundle_name
    written: list[Path] = []

    # Per-contract OHLCV under workspace/data/market_data/...
    for c in m["contracts"]:
        dst = contract_dir / f"{c}.csv"
        dst.write_bytes((pkg / "sort_by_contract" / f"{c}.csv").read_bytes())
        written.append(dst)

    # sort_by_date + trading_calendar at market_data root for this instrument.
    for fname in ("sort_by_date.csv", "trading_calendar.csv"):
        dst = market_data_root / fname
        dst.write_bytes((pkg / fname).read_bytes())
        written.append(dst)

    # main_contract.csv at raw_data_dir/{market}/{instrument_code}/.
    dst = main_root / "main_contract.csv"
    dst.write_bytes((pkg / "main_contract.csv").read_bytes())
    written.append(dst)

    return written
