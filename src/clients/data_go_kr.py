"""Common HTTP client for data.go.kr family of APIs.

Responsibilities:
- Inject service key
- Rate-limit outbound calls (token bucket)
- Retry transient failures (network / 5xx) with exponential backoff
- Detect API-level errors that come back with HTTP 200 (the portal's common pattern)
- Persist raw responses to disk so parse failures don't lose source data
- Page through `pageNo` / `numOfRows` cursors transparently
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import quote

import httpx
import xmltodict
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from src.clients.rate_limiter import TokenBucket
from src.config import get_settings
from src.logging_setup import get_logger

log = get_logger(__name__)


class DataGoKrError(RuntimeError):
    """Raised when the API returns a portal-level error (HTTP 200 with error body)."""

    def __init__(self, code: str, message: str, raw: Any = None) -> None:
        super().__init__(f"[{code}] {message}")
        self.code = code
        self.message = message
        self.raw = raw


class DataGoKrRateLimitError(DataGoKrError):
    """Server-side daily/per-minute quota exhausted — not retryable in-process."""


class DataGoKrTransientError(DataGoKrError):
    """Portal error worth retrying (system load, unknown failure)."""


# Portal error codes worth retrying vs. failing fast.
# Reference: https://www.data.go.kr/iim/api/selectAPIAcountView.do
_RETRYABLE_CODES = {"01", "02", "03", "04", "05", "20", "21", "99"}
_QUOTA_CODES = {"22"}  # LIMITED_NUMBER_OF_SERVICE_REQUESTS


class DataGoKrClient:
    """Synchronous client. Async needed? Wrap in a thread pool — most jobs are I/O-bound but small."""

    def __init__(
        self,
        service_key: str | None = None,
        rate_per_sec: float | None = None,
        timeout: float | None = None,
        raw_dir: Path | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        settings = get_settings()
        self.service_key = service_key if service_key is not None else settings.data_go_kr_service_key
        self.bucket = TokenBucket(rate_per_sec or settings.http_rate_limit_per_sec)
        self.raw_dir = Path(raw_dir or settings.raw_data_dir)
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        self._owns_client = client is None
        self._client = client or httpx.Client(timeout=timeout or settings.http_timeout_seconds)

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> "DataGoKrClient":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # ─── public ─────────────────────────────────────────────────────────

    def get(
        self,
        url: str,
        params: dict[str, Any],
        *,
        dataset_id: str,
        response_format: str = "json",
        save_raw: bool = True,
    ) -> dict[str, Any]:
        """Single page request. Returns parsed body (always dict shape)."""
        self.bucket.acquire()
        body, raw_text = self._do_request(url, params, response_format)
        if save_raw:
            self._persist_raw(dataset_id, params, raw_text, response_format)
        return body

    def paginate(
        self,
        url: str,
        params: dict[str, Any],
        *,
        dataset_id: str,
        response_format: str = "json",
        max_pages: int = 200,
        items_key: tuple[str, ...] = ("response", "body", "items"),
    ) -> Iterator[dict[str, Any]]:
        """Yield each item across pages. Stops when an empty/short page is returned."""
        page = int(params.get("pageNo", 1))
        page_size = int(params.get("numOfRows", 100))
        for _ in range(max_pages):
            paged = dict(params, pageNo=page, numOfRows=page_size)
            body = self.get(
                url, paged, dataset_id=dataset_id, response_format=response_format
            )
            items = _walk(body, items_key)
            normalized = _coerce_items(items)
            if not normalized:
                return
            yield from normalized
            if len(normalized) < page_size:
                return
            page += 1

    # ─── internals ───────────────────────────────────────────────────────

    @retry(
        reraise=True,
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=1, min=1, max=30),
        retry=retry_if_exception_type(
            (httpx.TransportError, httpx.HTTPStatusError, DataGoKrTransientError)
        ),
    )
    def _do_request(
        self, url: str, params: dict[str, Any], response_format: str
    ) -> tuple[dict[str, Any], str]:
        # The portal expects the service key as a raw query string (already URL-encoded by issuer).
        # httpx would re-encode it, so we append manually.
        merged = {k: v for k, v in params.items() if k != "ServiceKey"}
        query = "&".join(
            f"{k}={quote(str(v), safe='')}" for k, v in merged.items() if v is not None
        )
        full_url = (
            f"{url}?ServiceKey={self.service_key}&{query}"
            if query
            else f"{url}?ServiceKey={self.service_key}"
        )
        log.debug("data_go_kr.request", url=url, params=merged)
        resp = self._client.get(full_url)
        resp.raise_for_status()
        text = resp.text
        body = _parse_body(text, response_format)
        # Translate portal error codes into exception classes the retry filter understands.
        header = _walk(body, ("response", "header"))
        if isinstance(header, dict):
            code = str(header.get("resultCode", "")).strip()
            msg = str(header.get("resultMsg", "")).strip()
            if code and code not in {"00", "0", "NORMAL_SERVICE"}:
                if code in _QUOTA_CODES:
                    raise DataGoKrRateLimitError(code, msg, raw=body)
                if code in _RETRYABLE_CODES:
                    raise DataGoKrTransientError(code, msg, raw=body)
                raise DataGoKrError(code, msg, raw=body)
        return body, text

    def _persist_raw(
        self,
        dataset_id: str,
        params: dict[str, Any],
        raw_text: str,
        response_format: str,
    ) -> Path:
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        suffix = "json" if response_format == "json" else "xml"
        day_dir = self.raw_dir / dataset_id / ts[:8]
        day_dir.mkdir(parents=True, exist_ok=True)
        # filename keeps a hash-free, scannable hint of which page this was
        page = params.get("pageNo", "1")
        path = day_dir / f"{ts}_p{page}.{suffix}"
        path.write_text(raw_text, encoding="utf-8")
        return path


# ─── helpers ─────────────────────────────────────────────────────────────


def _parse_body(text: str, response_format: str) -> dict[str, Any]:
    fmt = response_format.lower()
    if fmt == "json":
        return json.loads(text)
    if fmt == "xml":
        # xmltodict preserves order; we collapse to plain dicts.
        return json.loads(json.dumps(xmltodict.parse(text)))
    raise ValueError(f"Unsupported response_format: {response_format}")


def _walk(body: Any, path: tuple[str, ...]) -> Any:
    cur: Any = body
    for key in path:
        if isinstance(cur, dict) and key in cur:
            cur = cur[key]
        else:
            return None
    return cur


def _coerce_items(items: Any) -> list[dict[str, Any]]:
    # Portal sometimes returns items as {"item": [...]}, sometimes {"item": {...}}, sometimes [...] directly.
    if items is None:
        return []
    if isinstance(items, list):
        return [i for i in items if isinstance(i, dict)]
    if isinstance(items, dict):
        if "item" in items:
            inner = items["item"]
            if isinstance(inner, list):
                return [i for i in inner if isinstance(i, dict)]
            if isinstance(inner, dict):
                return [inner]
            return []
        return [items]
    return []
