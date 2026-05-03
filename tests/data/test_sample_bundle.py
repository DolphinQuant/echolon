"""Verify the bundled SHFE sample is accessible via the data.sample API."""
from __future__ import annotations
from echolon.data.sample import (
    list_sample_bundles, get_sample_manifest, copy_sample_to,
)


def test_shfe_al_bundle_exists():
    assert "shfe_al" in list_sample_bundles()


def test_manifest_shape():
    m = get_sample_manifest("shfe_al")
    for k in ("instrument", "instrument_code", "market", "frequency",
              "bar_size", "contracts", "date_range"):
        assert k in m


def test_copy_lays_canonical_layout(tmp_path):
    project_root = tmp_path / "ws"
    written = copy_sample_to("shfe_al", project_root)

    m = get_sample_manifest("shfe_al")
    instrument, code, market = m["instrument"], m["instrument_code"], m["market"]

    # OHLCV under workspace/data/market_data/{market}/{instrument}/.
    market_data = project_root / "workspace" / "data" / "market_data" / market / instrument
    contract_dir = market_data / "sort_by_contract"
    for c in m["contracts"]:
        path = contract_dir / f"{c}.csv"
        assert path in written and path.exists()
        first = path.read_text().split("\n")[0]
        for col in ("contract", "date", "open", "close", "volume"):
            assert col in first

    # sort_by_date + trading_calendar at market_data root.
    for fname in ("sort_by_date.csv", "trading_calendar.csv"):
        assert (market_data / fname).exists()

    # main_contract.csv at raw_data_dir/{market}/{instrument_code}/.
    mc = project_root / "data" / market / code / "main_contract.csv"
    assert mc in written and mc.exists()
    assert "main_contract" in mc.read_text().split("\n")[0]
