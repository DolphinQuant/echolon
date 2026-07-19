"""Build empirical last-trade episodes for the three new CZCE products ap/cj/pk.

Panel-v5 (FV3 round-3) adds three CZCE products — ap (apple), cj (jujube/red date),
pk (peanut) — that were absent from p2_v4 and therefore have NO rows in the bundled
``echolon/markets/data/empirical_last_trades.csv``.  Without episodes, the strict
episode clock REFUSES their expired live contracts with :class:`NotImplementedError`
(CZCE has no operational encoded rule; expired contracts are empirical-only).  This
builder backfills those episodes purely from observed contract bars — no guessed rule —
exactly as the incumbent CZCE/DCE/SHFE episodes (``build_empirical_last_trade_data.py``)
and the GFEX episodes (``build_gfex_expiry_data.py``) were derived.

Keying convention (the CZCE decade-repeat trap).  CZCE's three-digit exchange codes
repeat every decade (AP601 = Jan-2016 AND Jan-2026), so the bundled table is
EPISODE-keyed: the same code carries multiple rows disambiguated by ``first_observation``.
The contract identifier stored here is exactly the code carried in the delivered bar
``symbol`` (e.g. ``AP1805`` — a four-digit unified code — split from its ``.ZF`` suffix),
because that is the identifier panel-v5 presents to the episode clock verbatim for these
products.  The delivered set also contains the native three-digit codes (``AP701``) for
the currently-listed contracts; every one of those delivers AFTER the data cutoff and is
dropped by the in-progress delivery-month filter below, so no code is stored twice.

Source: per-contract daily bars ``.csv.gz`` under
``<bars_root>/{ap,cj,pk}/*.csv.gz`` (xtdata_expansion_20260711).  The bar ``time`` column
is epoch-milliseconds in UTC; a single shared helper converts it to the Beijing trade
date (midnight-Beijing lands at 16:00 UTC the previous day — trap T8).

The write is strictly ADD-ONLY: every existing row (all other exchanges AND the incumbent
CZCE products) is preserved byte-for-byte; only ap/cj/pk rows are (re)written, so re-runs
are idempotent.  The final table is re-sorted by (exchange, contract, first_observation),
the same key the incumbent and GFEX builders use.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import gzip
import re
from pathlib import Path

NEW_PRODUCTS = ("ap", "cj", "pk")
EPISODE_GAP_DAYS = 180
_UNIX_EPOCH = dt.datetime(1970, 1, 1)
_BEIJING_OFFSET = dt.timedelta(hours=8)

_REPO_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_BARS_ROOT = (
    _REPO_ROOT.parents[1]
    / "output_bank/datasets/xtdata_expansion_20260711/raw/bars/CZCE"
)
_DEFAULT_EPISODES_CSV = _REPO_ROOT / "echolon/markets/data/empirical_last_trades.csv"

_EPISODE_FIELDS = ("exchange", "contract", "first_observation", "last_trade")


def beijing_date_from_epoch_ms(epoch_ms: int) -> dt.date:
    """Convert an epoch-millisecond UTC bar timestamp to its Beijing trade date.

    China Standard Time is a fixed UTC+8 (no DST since 1991), so shifting by eight hours
    before taking the calendar date recovers the true trade date from a midnight-Beijing
    bar stamp (the single conversion point for trap T8).
    """
    return (_UNIX_EPOCH + dt.timedelta(milliseconds=epoch_ms) + _BEIJING_OFFSET).date()


def _contract_trade_dates(path: Path) -> tuple[str, list[dt.date]]:
    """Return the suffix-stripped contract id and its sorted observed dates."""
    dates: set[dt.date] = set()
    contract: str | None = None
    with gzip.open(path, "rt", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            contract = row["symbol"].strip().split(".")[0].upper()
            dates.add(beijing_date_from_epoch_ms(int(row["time"])))
    if contract is None:
        raise ValueError(f"no bar rows in {path}")
    return contract, sorted(dates)


def _episodes(dates: list[dt.date]) -> list[list[dt.date]]:
    """Split observations into episodes whenever a gap exceeds 180 days."""
    episodes: list[list[dt.date]] = []
    start = 0
    for index in range(1, len(dates)):
        if (dates[index] - dates[index - 1]).days > EPISODE_GAP_DAYS:
            episodes.append(dates[start:index])
            start = index
    episodes.append(dates[start:])
    return episodes


def _delivery_month(contract: str, empirical: dt.date) -> tuple[int, int]:
    """Return the (year, month) delivery month of a CZCE contract identifier.

    Four-digit YYMM codes carry their own decade.  Three-digit YMM codes repeat every
    decade, so the decade is resolved from the episode's last observed date (the nearest
    matching year), exactly as ``build_empirical_last_trade_data.py`` resolves it.
    """
    four_digit = re.fullmatch(r"[A-Z]+(\d{2})(\d{2})", contract)
    if four_digit is not None:
        year_digits = int(four_digit.group(1))
        year = 2000 + year_digits if year_digits <= 50 else 1900 + year_digits
        return year, int(four_digit.group(2))
    three_digit = re.fullmatch(r"[A-Z]+(\d)(\d{2})", contract)
    if three_digit is None:
        raise ValueError(f"unexpected CZCE contract identifier: {contract}")
    year_digit = int(three_digit.group(1))
    candidates = [
        year
        for year in range(empirical.year - 2, empirical.year + 3)
        if year % 10 == year_digit
    ]
    return min(candidates, key=lambda year: abs(year - empirical.year)), int(
        three_digit.group(2)
    )


def _product_of(contract: str) -> str:
    """Return the lowercase product prefix (leading letters) of a contract code."""
    match = re.match(r"[A-Za-z]+", contract)
    if match is None:
        raise ValueError(f"uncontract-like identifier: {contract}")
    return match.group(0).lower()


def derive_new_czce(bars_root: Path) -> list[dict[str, str]]:
    """Return expired episode records for the new CZCE products ap/cj/pk."""
    contract_dates: dict[str, list[dt.date]] = {}
    calendar: set[dt.date] = set()
    for product in NEW_PRODUCTS:
        product_dir = bars_root / product
        for path in sorted(product_dir.glob("*.csv.gz")):
            contract, dates = _contract_trade_dates(path)
            if contract in contract_dates:
                raise ValueError(f"duplicate CZCE contract file for {contract}")
            contract_dates[contract] = dates
            calendar.update(dates)

    panel_end = max(calendar)
    records: list[dict[str, str]] = []
    for contract, dates in contract_dates.items():
        for episode in _episodes(dates):
            year, month = _delivery_month(contract, episode[-1])
            # A delivery month still in progress at the data cutoff is not expired.
            if (year, month) >= (panel_end.year, panel_end.month):
                continue
            records.append(
                {
                    "exchange": "CZCE",
                    "contract": contract,
                    "first_observation": episode[0].isoformat(),
                    "last_trade": episode[-1].isoformat(),
                }
            )
    return records


def _merge_episodes(episodes_csv: Path, new_records: list[dict[str, str]]) -> int:
    """Add-only merge: drop any existing ap/cj/pk CZCE rows, keep every other row, then
    append the new records and re-sort.  Preserves incumbent rows byte-for-byte and makes
    re-runs idempotent."""
    new_products = set(NEW_PRODUCTS)
    existing: list[dict[str, str]] = []
    if episodes_csv.exists():
        with episodes_csv.open("r", encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                if row["exchange"] == "CZCE" and _product_of(row["contract"]) in new_products:
                    continue
                existing.append(row)
    merged = existing + new_records
    episodes_csv.parent.mkdir(parents=True, exist_ok=True)
    with episodes_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=_EPISODE_FIELDS)
        writer.writeheader()
        writer.writerows(
            sorted(
                merged,
                key=lambda row: (
                    row["exchange"],
                    row["contract"],
                    row["first_observation"],
                ),
            )
        )
    return len(new_records)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bars-root", type=Path, default=_DEFAULT_BARS_ROOT)
    parser.add_argument("--episodes-csv", type=Path, default=_DEFAULT_EPISODES_CSV)
    args = parser.parse_args()

    records = derive_new_czce(args.bars_root)
    _merge_episodes(args.episodes_csv, records)
    per_product: dict[str, int] = {}
    for record in records:
        per_product[_product_of(record["contract"])] = (
            per_product.get(_product_of(record["contract"]), 0) + 1
        )
    summary = ", ".join(f"{p.upper()} {per_product.get(p, 0)}" for p in NEW_PRODUCTS)
    print(f"wrote {len(records)} expired CZCE ap/cj/pk episodes ({summary})")


if __name__ == "__main__":
    main()
