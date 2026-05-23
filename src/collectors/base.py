"""Collector base class.

Each collector follows the same skeleton:
  1. Pull config from datasets.yaml
  2. Call API via DataGoKrClient
  3. Map raw items → ORM-friendly dicts
  4. Upsert into SQLite
  5. Record an `ingestion_run` row
"""
from __future__ import annotations

import json
import traceback
from abc import ABC, abstractmethod
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterable, Iterator

from src.clients.data_go_kr import DataGoKrClient
from src.config import get_dataset, get_settings
from src.logging_setup import get_logger
from src.storage.db import session_scope
from src.storage.models import Base, IngestionRun
from src.storage.upsert import upsert_many

log = get_logger(__name__)


class BaseCollector(ABC):
    dataset_id: str
    model: type[Base]
    conflict_cols: list[str]

    def __init__(self, client: DataGoKrClient | None = None) -> None:
        self.config = get_dataset(self.dataset_id)
        self._owns_client = client is None
        self.client = client or DataGoKrClient()
        self.log = log.bind(dataset_id=self.dataset_id)

    def close(self) -> None:
        if self._owns_client:
            self.client.close()

    def __enter__(self) -> "BaseCollector":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # ─── subclass contract ──────────────────────────────────────────────

    @abstractmethod
    def fetch(self, **kwargs: Any) -> Iterable[dict[str, Any]]:
        """Yield raw items from the API. May call self.client.paginate(...)."""

    @abstractmethod
    def parse(self, item: dict[str, Any]) -> dict[str, Any] | None:
        """Convert one raw item to an ORM-ready dict. Return None to skip."""

    # ─── orchestration ──────────────────────────────────────────────────

    def run(self, **kwargs: Any) -> int:
        """Fetch → parse → upsert. Returns rows-attempted count."""
        with self._ingestion_run(kwargs) as run:
            rows: list[dict[str, Any]] = []
            for raw in self.fetch(**kwargs):
                try:
                    parsed = self.parse(raw)
                except Exception as e:
                    self.log.warning("parse_failed", error=str(e), raw=raw)
                    continue
                if parsed is not None:
                    rows.append(parsed)
            self.log.info("rows_parsed", count=len(rows))
            with session_scope() as session:
                upsert_many(
                    session,
                    self.model,
                    rows,
                    conflict_cols=self.conflict_cols,
                )
            run.rows_inserted = len(rows)
            return len(rows)

    @contextmanager
    def _ingestion_run(self, params: dict[str, Any]) -> Iterator[IngestionRun]:
        with ingestion_run(self.dataset_id, params) as run:
            yield run


@contextmanager
def ingestion_run(dataset_id: str, params: dict[str, Any]) -> Iterator[IngestionRun]:
    """Reusable ingestion-run lifecycle. Used by BaseCollector and file-based collectors alike."""
    with session_scope() as session:
        run = IngestionRun(
            dataset_id=dataset_id,
            started_at=datetime.now(timezone.utc).replace(tzinfo=None),
            status="running",
            params_json=_safe_json(params),
        )
        session.add(run)
        session.flush()
        run_id = run.id
    try:
        with session_scope() as session:
            run = session.get(IngestionRun, run_id)
            assert run is not None
            yield run
            run.status = "success"
            run.finished_at = datetime.now(timezone.utc).replace(tzinfo=None)
    except Exception as e:
        with session_scope() as session:
            run = session.get(IngestionRun, run_id)
            assert run is not None
            run.status = "error"
            run.finished_at = datetime.now(timezone.utc).replace(tzinfo=None)
            run.error = f"{type(e).__name__}: {e}\n{traceback.format_exc()[:1800]}"
        raise


def _safe_json(obj: Any) -> str:
    try:
        return json.dumps(obj, ensure_ascii=False, default=str)[:2000]
    except Exception:
        return str(obj)[:2000]


def to_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None


def to_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(float(str(value).replace(",", "")))
    except (TypeError, ValueError):
        return None
