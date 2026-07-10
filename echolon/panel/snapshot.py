"""Load and view immutable panel snapshots."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
from pathlib import Path
from typing import Any

import pandas as pd

from .models import CurvePoint, InstrumentMeta, PanelManifest


BAR_COLUMNS = [
    "open",
    "high",
    "low",
    "close",
    "settle",
    "open_raw",
    "high_raw",
    "low_raw",
    "close_raw",
    "settle_raw",
    "open_adj",
    "high_adj",
    "low_adj",
    "close_adj",
    "settle_adj",
    "adj_factor",
    "volume",
    "open_interest",
    "contract",
]

CONTRACT_COLUMNS = [
    "symbol",
    "open",
    "high",
    "low",
    "close",
    "settle",
    "volume",
    "open_interest",
    "contract",
]

CURVE_COLUMNS = [
    "near_contract",
    "near_settle",
    "far_contract",
    "far_settle",
    "days_between",
]


def _parse_date(value: str | dt.date) -> dt.date:
    if isinstance(value, dt.date):
        return value
    return dt.date.fromisoformat(value)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read_csv_with_date(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    if "date" not in df.columns:
        raise ValueError(f"{path} missing required date column")
    df["date"] = pd.to_datetime(df["date"]).dt.date
    return df.set_index("date").sort_index()


class PanelView:
    """Read-only view of all panel facts known as of one date."""

    def __init__(self, panel: "PanelData", date: dt.date) -> None:
        self._panel = panel
        self.date = date

    def bars(self, instrument: str, lookback: int) -> pd.DataFrame:
        if lookback <= 0:
            raise ValueError("lookback must be positive")
        instrument_id = instrument.lower()
        if instrument_id not in self._panel._bars:
            raise KeyError(instrument)
        bars = self._panel._bars[instrument_id]
        visible = bars.loc[bars.index <= self.date, BAR_COLUMNS]
        return visible.tail(lookback).copy()

    def contract_bar(self, instrument: str, contract: str) -> pd.Series | None:
        """Return the raw row for a specific listed contract on the view date."""
        instrument_id = instrument.lower()
        contracts = self._panel._contracts.get(instrument_id)
        if contracts is None or self.date not in contracts.index:
            return None
        rows = contracts.loc[[self.date]]
        match = rows[rows["contract"].astype(str) == str(contract)]
        if match.empty:
            return None
        return match.iloc[0].copy()

    def curve_history(self, instrument: str, lookback: int) -> pd.DataFrame:
        """Return up to ``lookback`` curve rows dated on or before the view date.

        Mirrors :meth:`bars` no-lookahead semantics for the near/far curve
        series so curve-history signals (basis momentum, carry change) cannot
        read past the view date by construction. Instruments without a curve
        file return an empty frame with the canonical curve columns.
        """
        if lookback <= 0:
            raise ValueError("lookback must be positive")
        instrument_id = instrument.lower()
        curves = self._panel._curves.get(instrument_id)
        if curves is None:
            return pd.DataFrame(columns=CURVE_COLUMNS)
        visible = curves.loc[curves.index <= self.date, CURVE_COLUMNS]
        return visible.tail(lookback).copy()

    def curve(self, instrument: str) -> CurvePoint | None:
        instrument_id = instrument.lower()
        curves = self._panel._curves.get(instrument_id)
        if curves is None or self.date not in curves.index:
            return None
        row = curves.loc[self.date]
        return CurvePoint(
            near_contract=str(row["near_contract"]),
            near_settle=float(row["near_settle"]),
            far_contract=str(row["far_contract"]),
            far_settle=float(row["far_settle"]),
            days_between=int(row["days_between"]),
        )

    def meta(self, instrument: str) -> InstrumentMeta:
        instrument_id = instrument.lower()
        if instrument_id not in self._panel._meta:
            raise KeyError(instrument)
        return self._panel._meta[instrument_id]


class PanelData:
    """Immutable multi-instrument daily panel loaded from a snapshot directory."""

    def __init__(
        self,
        *,
        snapshot_dir: Path,
        manifest: PanelManifest,
        bars: dict[str, pd.DataFrame],
        curves: dict[str, pd.DataFrame],
        contracts: dict[str, pd.DataFrame],
        meta: dict[str, InstrumentMeta],
    ) -> None:
        self.snapshot_dir = snapshot_dir
        self.manifest = manifest
        self.instruments = list(manifest.instruments)
        self.snapshot_version = manifest.version
        self._bars = bars
        self._curves = curves
        self._contracts = contracts
        self._meta = meta
        self.calendar = self._build_calendar()

    @classmethod
    def load(cls, snapshot_dir: Path) -> "PanelData":
        snapshot_path = Path(snapshot_dir)
        manifest_path = snapshot_path / "manifest.json"
        manifest = PanelManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
        cls._verify_manifest_hashes(snapshot_path, manifest)

        bars = {
            instrument: _normalize_bar_frame(_read_csv_with_date(snapshot_path / "bars" / f"{instrument}.csv"))
            for instrument in manifest.instruments
        }
        curves: dict[str, pd.DataFrame] = {}
        contracts: dict[str, pd.DataFrame] = {}
        for instrument in manifest.instruments:
            curve_path = snapshot_path / "curves" / f"{instrument}.csv"
            if curve_path.exists():
                curves[instrument] = _read_csv_with_date(curve_path)
            contracts_path = snapshot_path / "contracts" / f"{instrument}.csv"
            if contracts_path.exists():
                contracts[instrument] = _normalize_contract_frame(_read_csv_with_date(contracts_path))

        meta = cls._load_meta(snapshot_path / "meta" / "instruments.csv")
        for instrument in manifest.instruments:
            if instrument not in meta:
                raise ValueError(f"missing metadata for instrument {instrument}")

        return cls(
            snapshot_dir=snapshot_path,
            manifest=manifest,
            bars=bars,
            curves=curves,
            contracts=contracts,
            meta=meta,
        )

    @staticmethod
    def _verify_manifest_hashes(snapshot_dir: Path, manifest: PanelManifest) -> None:
        for relpath, expected_hash in manifest.files.items():
            path = snapshot_dir / relpath
            if not path.exists():
                raise ValueError(f"manifest file missing: {relpath}")
            actual_hash = _sha256(path)
            if actual_hash != expected_hash:
                raise ValueError(
                    f"manifest hash mismatch for {relpath}: "
                    f"expected {expected_hash}, got {actual_hash}"
                )

    @staticmethod
    def _load_meta(path: Path) -> dict[str, InstrumentMeta]:
        df = pd.read_csv(path)
        records: dict[str, InstrumentMeta] = {}
        for row in df.to_dict(orient="records"):
            normalized = {key: _none_if_nan(value) for key, value in row.items()}
            instrument_id = str(normalized["instrument_id"]).lower()
            records[instrument_id] = InstrumentMeta(
                instrument_id=instrument_id,
                sector=str(normalized["sector"]),
                multiplier=float(normalized["multiplier"]),
                tick=float(normalized["tick"]),
                margin_rate=float(normalized["margin_rate"]),
                commission=float(normalized["commission"]),
                commission_type=str(normalized["commission_type"]),
                close_today_commission=(
                    None
                    if normalized["close_today_commission"] is None
                    else float(normalized["close_today_commission"])
                ),
                currency=str(normalized["currency"]),
            )
        return records

    def _build_calendar(self) -> list[dt.date]:
        dates: set[dt.date] = set()
        for bars in self._bars.values():
            dates.update(bars.index)
        return sorted(dates)

    def view(self, date: dt.date | str) -> PanelView:
        view_date = _parse_date(date)
        if view_date not in self.calendar:
            raise KeyError(view_date.isoformat())
        return PanelView(self, view_date)


def _none_if_nan(value: Any) -> Any:
    if pd.isna(value):
        return None
    if value == "":
        return None
    return value


def _normalize_bar_frame(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    for column in ("open", "high", "low", "close", "settle"):
        raw = f"{column}_raw"
        adj = f"{column}_adj"
        if raw not in out:
            out[raw] = out[column]
        if adj not in out:
            out[adj] = out[column]
        out[column] = out[adj]
    if "adj_factor" not in out:
        out["adj_factor"] = 1.0
    return out


def _normalize_contract_frame(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    if "contract" not in out and "symbol" in out:
        out["contract"] = out["symbol"]
    if "symbol" not in out and "contract" in out:
        out["symbol"] = out["contract"]
    return out
