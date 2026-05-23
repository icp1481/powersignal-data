"""D4 — Monthly fuel cost (LNG/coal/oil) summary.

Endpoint: data.go.kr 15099765. Runs monthly. Fuel types come back in a list.
"""
from __future__ import annotations

from typing import Any, Iterable

from src.collectors.base import BaseCollector, to_float, to_int
from src.storage.models import FuelCostMonthly


_YEAR_KEYS = ("year", "baseYear", "stdYear", "STD_YR")
_MONTH_KEYS = ("month", "baseMonth", "stdMonth", "STD_MM")
_PERIOD_KEYS = ("baseYm", "stdYm", "yyyymm", "period")
_FUEL_TYPE_KEYS = ("fuelType", "fuelCd", "fuelName", "FUEL_TP")
_FUEL_UNIT_COST_KEYS = ("fuelUnitCost", "fuelUnitPrice", "FUEL_UNIT_COST")
_HEAT_UNIT_COST_KEYS = ("heatUnitCost", "heatUnitPrice", "HEAT_UNIT_COST")
_PER_KWH_KEYS = ("costPerKwh", "fuelCostPerKwh", "PER_KWH_COST")


def _first(item: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for k in keys:
        if k in item and item[k] not in (None, ""):
            return item[k]
    return None


def _split_period(value: Any) -> tuple[int | None, int | None]:
    if value is None:
        return (None, None)
    s = str(value).strip()
    if len(s) == 6 and s.isdigit():
        return (int(s[:4]), int(s[4:]))
    if len(s) == 7 and s[4] in "-/":
        return (int(s[:4]), int(s[5:]))
    return (None, None)


class FuelCostCollector(BaseCollector):
    dataset_id = "D4"
    model = FuelCostMonthly
    conflict_cols = ["period_year", "period_month", "fuel_type"]

    def fetch(self, **kwargs: Any) -> Iterable[dict[str, Any]]:
        base = self.config["base_url"]
        endpoint = self.config["endpoints"]["monthly"]
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
        year = to_int(_first(item, _YEAR_KEYS))
        month = to_int(_first(item, _MONTH_KEYS))
        if year is None or month is None:
            y, m = _split_period(_first(item, _PERIOD_KEYS))
            year, month = year or y, month or m
        fuel_type = _first(item, _FUEL_TYPE_KEYS)
        if year is None or month is None or fuel_type is None:
            self.log.warning("lng.missing_keys", item=item)
            return None
        return {
            "period_year": year,
            "period_month": month,
            "fuel_type": str(fuel_type).upper(),
            "fuel_unit_cost": to_float(_first(item, _FUEL_UNIT_COST_KEYS)),
            "heat_unit_cost": to_float(_first(item, _HEAT_UNIT_COST_KEYS)),
            "cost_per_kwh": to_float(_first(item, _PER_KWH_KEYS)),
        }
