"""Centralized configuration loader.

Reads `.env` for secrets/runtime settings and `config/datasets.yaml` for dataset definitions.
All collectors and CLI scripts go through this module — no scattered `os.getenv` calls.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATASETS_FILE = PROJECT_ROOT / "config" / "datasets.yaml"


class Settings(BaseSettings):
    """Runtime settings sourced from `.env` (or process environment)."""

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    data_go_kr_service_key: str = Field(default="", description="공공데이터포털 서비스키")
    kma_service_key: str = Field(default="", description="기상청 서비스키 — 비어 있으면 공공데이터포털 키로 폴백")

    database_url: str = Field(default="sqlite:///./data/powersignal.db")
    raw_data_dir: Path = Field(default=PROJECT_ROOT / "data" / "raw")
    parsed_data_dir: Path = Field(default=PROJECT_ROOT / "data" / "parsed")
    static_data_dir: Path = Field(default=PROJECT_ROOT / "data" / "static")

    http_timeout_seconds: float = Field(default=30.0)
    http_max_retries: int = Field(default=5)
    http_rate_limit_per_sec: float = Field(default=2.0)

    log_level: str = Field(default="INFO")

    @property
    def kma_key(self) -> str:
        return self.kma_service_key or self.data_go_kr_service_key


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


@lru_cache(maxsize=1)
def load_dataset_config(path: Path | None = None) -> dict[str, Any]:
    """Load and cache dataset YAML."""
    cfg_path = path or DEFAULT_DATASETS_FILE
    with cfg_path.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def get_dataset(dataset_id: str) -> dict[str, Any]:
    """Look up a dataset definition by ID (D1, D2, ...)."""
    cfg = load_dataset_config()
    datasets = cfg.get("datasets", {})
    if dataset_id not in datasets:
        raise KeyError(f"Dataset {dataset_id!r} not defined in datasets.yaml")
    return datasets[dataset_id]
