"""D5/D6 file ingestion tests — including encoding detection."""
from __future__ import annotations

from pathlib import Path

import pandas as pd
from sqlalchemy import select

from src.collectors.dr_history import DrEconomicCollector, DrReliabilityCollector
from src.storage.db import session_scope
from src.storage.models import DrTransactionMonthly, IngestionRun


def _write_csv(path: Path, encoding: str) -> None:
    df = pd.DataFrame(
        {
            "기간": ["2026-03", "2026-03", "2026-04"],
            "자원명": ["공장A", "공장B", "공장A"],
            "입찰량": [1000, 500, 1200],
            "낙찰량": [800, 0, 950],
            "정산금": [80000000, 0, 95000000],
        }
    )
    df.to_csv(path, index=False, encoding=encoding)


def test_ingest_local_csv_utf8(tmp_path: Path):
    csv = tmp_path / "dr_econ.csv"
    _write_csv(csv, encoding="utf-8-sig")

    collector = DrEconomicCollector()
    inserted = collector.ingest_file(csv)
    assert inserted == 3

    with session_scope() as s:
        rows = s.execute(
            select(DrTransactionMonthly).order_by(DrTransactionMonthly.period_month)
        ).scalars().all()
        assert len(rows) == 3
        assert all(r.dr_type == "economic" for r in rows)
        march_factory_a = next(
            r for r in rows if r.period_month == 3 and r.resource_name == "공장A"
        )
        assert march_factory_a.bid_mwh == 1000.0
        assert march_factory_a.cleared_mwh == 800.0
        assert march_factory_a.settlement_krw == 80000000.0

        runs = s.execute(select(IngestionRun)).scalars().all()
        assert len(runs) == 1
        assert runs[0].dataset_id == "D5"
        assert runs[0].status == "success"


def test_ingest_local_csv_cp949(tmp_path: Path):
    csv = tmp_path / "dr_rel.csv"
    _write_csv(csv, encoding="cp949")

    collector = DrReliabilityCollector()
    inserted = collector.ingest_file(csv)
    assert inserted == 3

    with session_scope() as s:
        rows = s.execute(select(DrTransactionMonthly)).scalars().all()
        assert all(r.dr_type == "reliability" for r in rows)


def test_ingest_is_idempotent(tmp_path: Path):
    csv = tmp_path / "dr_econ.csv"
    _write_csv(csv, encoding="utf-8-sig")
    collector = DrEconomicCollector()
    collector.ingest_file(csv)
    collector.ingest_file(csv)  # re-ingest
    with session_scope() as s:
        rows = s.execute(select(DrTransactionMonthly)).scalars().all()
        assert len(rows) == 3  # upsert, not duplicate
