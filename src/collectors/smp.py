"""D1 — SMP and demand forecast (하루전 발전계획용).

Endpoint: data.go.kr 15131225 (신버전. 구버전 15076302 사용 금지)
Returns one row per (trade_date, trade_hour, region).

Notes:
- trade_hour follows end-of-interval convention (6 = 05:00~06:00). We preserve as-is.
- region 'land' and 'jeju' are both returned; we store both.
- Field names in the response (e.g. 'tradeDt', 'tradeHh', 'jejuSmp', 'landSmp') are best
  inferred at integration time — the API spec on the portal is the source of truth.
  We map flexibly to cope with case variations.
"""
from __future__ import annotations

from typing import Any, Iterable

from src.collectors.base import BaseCollector, to_float
from src.storage.models import SmpHourly
from src.transform.time_normalize import (
    normalize_region,
    parse_trade_date,
    parse_trade_hour,
)


# Multiple possible field names — portal docs vary in capitalization and naming.
_DATE_KEYS = ("tradeDt", "trade_dt", "tradeDate", "baseDate", "stdDate", "STD_DT")
_HOUR_KEYS = ("tradeHh", "trade_hh", "tradeHour", "hh", "stdHh", "STD_HH")
_REGION_KEYS = ("region", "areaCd", "areaName", "regionCd", "REGION")
_SMP_KEYS = ("smp", "smpPrice", "SMP", "SMP_PRICE")
_DEMAND_KEYS = ("demand", "demandFcst", "demandForecast", "FORECAST_DEMAND")


def _first(item: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for k in keys:
        if k in item and item[k] not in (None, ""):
            return item[k]
    return None


class SmpCollector(BaseCollector):
    dataset_id = "D1"
    model = SmpHourly
    conflict_cols = ["trade_date", "trade_hour", "region"]

    def fetch(self, **kwargs: Any) -> Iterable[dict[str, Any]]:
        base = self.config["base_url"]
        endpoint = self.config["endpoints"]["list"]
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
        date_raw = _first(item, _DATE_KEYS)
        hour_raw = _first(item, _HOUR_KEYS)
        if date_raw is None or hour_raw is None:
            self.log.warning("smp.missing_date_or_hour", item=item)
            return None

        # Some response shapes split SMP by region into separate fields (landSmp/jejuSmp).
        # In that case we'd emit two rows; but parse() can only emit one. So we treat that
        # shape via fetch(): when keys like 'landSmp' exist, we synthesize separate items
        # per region. Detected here by absence of an explicit region key.
        region = _first(item, _REGION_KEYS)
        if region is None and "landSmp" in item and "jejuSmp" in item:
            self.log.warning(
                "smp.combined_region_row_should_be_split_in_fetch",
                hint="adjust SmpCollector.fetch to split combined rows",
            )
            return None

        return {
            "trade_date": parse_trade_date(date_raw),
            "trade_hour": parse_trade_hour(hour_raw),
            "region": normalize_region(region),
            "smp_krw_per_kwh": to_float(_first(item, _SMP_KEYS)),
            "demand_forecast_mw": to_float(_first(item, _DEMAND_KEYS)),
        }
