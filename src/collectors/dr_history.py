"""D5/D6 — DR transaction history (economic / reliability).

The portal serves these as monthly CSV/Excel downloads, not OpenAPI. We support
two intake paths:
  1. Local file: caller provides a path that was downloaded manually.
  2. Remote URL: configured in datasets.yaml; we fetch it and persist raw.

CSV encoding is autodetected from a candidate list — Korean public CSVs are
typically CP949 / EUC-KR but newer exports come in UTF-8 with BOM.
"""
from __future__ import annotations

import io
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import chardet
import httpx
import pandas as pd

from src.collectors.base import ingestion_run, to_float
from src.config import get_dataset, get_settings
from src.logging_setup import get_logger
from src.storage.db import session_scope
from src.storage.models import DrTransactionMonthly
from src.storage.upsert import upsert_many

log = get_logger(__name__)


# Heuristic column-name maps — Korean column headers vary across years.
_PERIOD_HINTS = ("기간", "거래월", "정산월", "period", "ym")
_RESOURCE_HINTS = ("자원명", "사업자명", "참여사업자", "수요반응자원", "resource")
_BID_HINTS = ("입찰량", "응찰량", "bid")
_CLEARED_HINTS = ("낙찰량", "확정량", "이행량", "cleared")
_SETTLEMENT_HINTS = ("정산금", "정산액", "settlement", "amount")


def _match_col(columns: list[str], hints: tuple[str, ...]) -> str | None:
    lc_cols = [(c, c.lower()) for c in columns]
    for hint in hints:
        for original, lc in lc_cols:
            if hint.lower() in lc:
                return original
    return None


def _split_period(value: Any) -> tuple[int | None, int | None]:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return (None, None)
    s = str(value).strip().replace(".", "-").replace("/", "-")
    if len(s) >= 7 and s[:4].isdigit() and "-" in s[4:]:
        parts = s.split("-")
        return (int(parts[0]), int(parts[1][:2]))
    if len(s) == 6 and s.isdigit():
        return (int(s[:4]), int(s[4:]))
    if len(s) == 4 and s.isdigit():  # year only — month unknown
        return (int(s), None)
    return (None, None)


class DrHistoryCollector:
    """File-based collector. Subclasses set dataset_id + dr_type."""

    model = DrTransactionMonthly
    conflict_cols = ["period_year", "period_month", "dr_type", "resource_name"]
    dataset_id: str = ""
    dr_type: str = ""

    def __init__(self) -> None:
        self.config = get_dataset(self.dataset_id)
        self.log = log.bind(dataset_id=self.dataset_id)

    # ─── public API for file ingestion ────────────────────────────────────

    def ingest_file(self, path: Path) -> int:
        df, raw_bytes = self._read_local(path)
        return self._persist(df, source_hint=str(path), raw_bytes=raw_bytes)

    def ingest_url(self, url: str | None = None) -> int:
        url = url or self.config.get("download_url")
        if not url:
            raise ValueError(
                f"{self.dataset_id}: no download_url in datasets.yaml and none provided"
            )
        raw_bytes = self._download(url)
        df = self._decode_to_df(raw_bytes)
        return self._persist(df, source_hint=url, raw_bytes=raw_bytes)

    # ─── internals ────────────────────────────────────────────────────────

    def _download(self, url: str) -> bytes:
        settings = get_settings()
        with httpx.Client(timeout=settings.http_timeout_seconds, follow_redirects=True) as c:
            resp = c.get(url)
            resp.raise_for_status()
            return resp.content

    def _read_local(self, path: Path) -> tuple[pd.DataFrame, bytes]:
        raw = path.read_bytes()
        if path.suffix.lower() in {".xlsx", ".xls"}:
            df = pd.read_excel(io.BytesIO(raw))
        else:
            df = self._decode_to_df(raw)
        return df, raw

    def _decode_to_df(self, raw: bytes) -> pd.DataFrame:
        encodings = self.config.get("encoding_candidates", ["utf-8-sig", "cp949"])
        last_err: Exception | None = None
        # 1) try configured candidates
        for enc in encodings:
            try:
                return pd.read_csv(io.BytesIO(raw), encoding=enc)
            except (UnicodeDecodeError, UnicodeError) as e:
                last_err = e
                continue
            except pd.errors.ParserError as e:
                last_err = e
                continue
        # 2) chardet fallback
        detected = chardet.detect(raw)
        if detected and detected.get("encoding"):
            try:
                return pd.read_csv(io.BytesIO(raw), encoding=detected["encoding"])
            except Exception as e:  # noqa: BLE001
                last_err = e
        raise RuntimeError(f"Failed to decode CSV for {self.dataset_id}: {last_err}")

    def _persist(self, df: pd.DataFrame, *, source_hint: str, raw_bytes: bytes) -> int:
        self._save_raw(raw_bytes, source_hint)
        rows = list(self._map_rows(df))
        with ingestion_run(self.dataset_id, {"source": source_hint, "row_count": len(rows)}) as run:
            with session_scope() as session:
                upsert_many(session, self.model, rows, conflict_cols=self.conflict_cols)
            run.rows_inserted = len(rows)
        return len(rows)

    def _save_raw(self, raw: bytes, hint: str) -> None:
        settings = get_settings()
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        day_dir = Path(settings.raw_data_dir) / self.dataset_id / ts[:8]
        day_dir.mkdir(parents=True, exist_ok=True)
        suffix = ".xlsx" if hint.lower().endswith((".xlsx", ".xls")) else ".csv"
        (day_dir / f"{ts}{suffix}").write_bytes(raw)

    def _map_rows(self, df: pd.DataFrame) -> Iterable[dict[str, Any]]:
        cols = list(df.columns)
        period_col = _match_col(cols, _PERIOD_HINTS)
        resource_col = _match_col(cols, _RESOURCE_HINTS)
        bid_col = _match_col(cols, _BID_HINTS)
        cleared_col = _match_col(cols, _CLEARED_HINTS)
        settle_col = _match_col(cols, _SETTLEMENT_HINTS)

        if period_col is None or resource_col is None:
            raise RuntimeError(
                f"{self.dataset_id}: missing essential columns. "
                f"Found: {cols}. Need period+resource hints."
            )

        for _, row in df.iterrows():
            year, month = _split_period(row[period_col])
            if year is None or month is None:
                continue
            resource_name = str(row[resource_col]).strip()
            if not resource_name or resource_name.lower() == "nan":
                continue
            raw_columns = {c: (None if pd.isna(row[c]) else _scalar(row[c])) for c in cols}
            yield {
                "period_year": year,
                "period_month": month,
                "dr_type": self.dr_type,
                "resource_name": resource_name[:128],
                "bid_mwh": to_float(row[bid_col]) if bid_col else None,
                "cleared_mwh": to_float(row[cleared_col]) if cleared_col else None,
                "settlement_krw": to_float(row[settle_col]) if settle_col else None,
                "raw_columns_json": json.dumps(raw_columns, ensure_ascii=False, default=str)[
                    :4000
                ],
            }

def _scalar(v: Any) -> Any:
    if isinstance(v, (str, int, float, bool)) or v is None:
        return v
    return str(v)


class DrEconomicCollector(DrHistoryCollector):
    dataset_id = "D5"
    dr_type = "economic"


class DrReliabilityCollector(DrHistoryCollector):
    dataset_id = "D6"
    dr_type = "reliability"
