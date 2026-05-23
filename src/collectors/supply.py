"""D2 — Real-time supply / demand snapshot.

Endpoint: data.go.kr 15056640. Returns a small payload of the latest reading.
We just take whatever the API gives and stamp it with our observation time.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Iterable

from src.collectors.base import BaseCollector, to_float
from src.storage.models import SupplySnapshot


_SUPPLY_KEYS = ("supplyCapacity", "supplyCap", "supplyCapacityMw", "supply_capacity")
_DEMAND_KEYS = ("currentDemand", "currDemand", "demand", "currentLoad")
_RESERVE_KEYS = ("reserve", "reservePower", "reserveCap")
_RATIO_KEYS = ("reserveRatio", "supplyReserveRate", "reserveRate")
_TIME_KEYS = ("baseDatetime", "baseDtm", "observedAt", "tm", "ttm", "datetime")


def _first(item: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for k in keys:
        if k in item and item[k] not in (None, ""):
            return item[k]
    return None


def _parse_dt(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    if value is None:
        return datetime.utcnow()
    s = str(value).strip()
    # Try a couple of common formats. Fall back to "now" rather than raising —
    # this endpoint's exact field name varies and we don't want to lose the row.
    for fmt in ("%Y%m%d%H%M%S", "%Y-%m-%d %H:%M:%S", "%Y%m%d%H%M", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return datetime.utcnow()


class SupplyCollector(BaseCollector):
    dataset_id = "D2"
    model = SupplySnapshot
    conflict_cols = ["observed_at"]

    def fetch(self, **kwargs: Any) -> Iterable[dict[str, Any]]:
        base = self.config["base_url"]
        endpoint = self.config["endpoints"]["current"]
        url = base.rstrip("/") + endpoint
        params = dict(self.config.get("default_params", {}))
        params.update({k: v for k, v in kwargs.items() if v is not None})
        yield from self.client.paginate(
            url,
            params,
            dataset_id=self.dataset_id,
            response_format=self.config.get("response_format", "json"),
        )

    def parse(self, item: dict[str, Any]) -> dict[str, Any] | None:
        return {
            "observed_at": _parse_dt(_first(item, _TIME_KEYS)),
            "supply_capacity_mw": to_float(_first(item, _SUPPLY_KEYS)),
            "current_demand_mw": to_float(_first(item, _DEMAND_KEYS)),
            "reserve_mw": to_float(_first(item, _RESERVE_KEYS)),
            "reserve_ratio_pct": to_float(_first(item, _RATIO_KEYS)),
        }
