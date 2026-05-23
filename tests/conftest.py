"""Shared pytest fixtures.

The default fixture pattern:
- Each test runs against a fresh in-memory SQLite DB (set via DATABASE_URL env override).
- Settings cache is cleared so the override takes effect.
- HTTP calls are mocked with `respx` — no network in CI.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

# Override DB + service key BEFORE any src.* import wires them in.
os.environ["DATA_GO_KR_SERVICE_KEY"] = "TEST_KEY"
os.environ["KMA_SERVICE_KEY"] = "TEST_KMA_KEY"
os.environ["HTTP_RATE_LIMIT_PER_SEC"] = "1000"  # disable throttling in tests


@pytest.fixture(autouse=True)
def isolated_storage(monkeypatch, tmp_path: Path):
    """Each test gets its own SQLite file + raw dir. No cross-test bleed."""
    db_file = tmp_path / "test.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file}")
    monkeypatch.setenv("RAW_DATA_DIR", str(tmp_path / "raw"))
    monkeypatch.setenv("PARSED_DATA_DIR", str(tmp_path / "parsed"))
    monkeypatch.setenv("STATIC_DATA_DIR", str(tmp_path / "static"))

    # Reset cached singletons in src.config and src.storage.db so they pick up new env.
    from src import config as cfg
    from src.storage import db as dbmod

    cfg.get_settings.cache_clear()
    cfg.load_dataset_config.cache_clear()
    dbmod._engine = None
    dbmod._SessionLocal = None

    dbmod.init_db()

    yield

    # cleanup
    cfg.get_settings.cache_clear()
    cfg.load_dataset_config.cache_clear()
    dbmod._engine = None
    dbmod._SessionLocal = None
