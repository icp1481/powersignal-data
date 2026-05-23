"""D3 — KMA ASOS hourly weather observations.

Endpoint: data.go.kr 1360000 AsosHourlyInfoService.

Iteration model differs from D1/D2:
- One API call per (station, date-range). We loop stations × date-window.
- Each item is a single hour observation; we upsert keyed by (station, observed_at).
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Iterable

from src.clients.data_go_kr import DataGoKrClient
from src.collectors.base import BaseCollector, to_float
from src.config import get_settings
from src.storage.models import WeatherHourly
from src.transform.time_normalize import parse_kma_hourly_timestamp


def _date_fmt(d: date) -> str:
    return d.strftime("%Y%m%d")


class WeatherCollector(BaseCollector):
    dataset_id = "D3"
    model = WeatherHourly
    conflict_cols = ["station_id", "observed_at"]

    def __init__(self, client: DataGoKrClient | None = None) -> None:
        # KMA endpoint may need a distinct service key. Build client up-front
        # so BaseCollector doesn't pull from the default data.go.kr key.
        if client is None:
            client = DataGoKrClient(service_key=get_settings().kma_key)
        super().__init__(client=client)

    def fetch(
        self,
        *,
        start_date: date | None = None,
        end_date: date | None = None,
        stations: list[int] | None = None,
        **kwargs: Any,
    ) -> Iterable[dict[str, Any]]:
        end = end_date or (datetime.utcnow().date() - timedelta(days=1))
        start = start_date or end
        stations = stations or list(self.config.get("default_stations", []))
        if not stations:
            raise ValueError("WeatherCollector requires at least one station_id")

        base = self.config["base_url"]
        endpoint = self.config["endpoints"]["hourly"]
        url = base.rstrip("/") + endpoint

        for station_id in stations:
            params = dict(self.config.get("default_params", {}))
            params.update(
                {
                    "startDt": _date_fmt(start),
                    "startHh": "00",
                    "endDt": _date_fmt(end),
                    "endHh": "23",
                    "stnIds": station_id,
                }
            )
            for item in self.client.paginate(
                url,
                params,
                dataset_id=self.dataset_id,
                response_format=self.config.get("response_format", "json"),
            ):
                # Inject station_id into item so parse() can use it without context tracking
                item.setdefault("_station_id", station_id)
                yield item

    def parse(self, item: dict[str, Any]) -> dict[str, Any] | None:
        station_id = item.get("_station_id") or item.get("stnId") or item.get("stationId")
        tm = item.get("tm") or item.get("baseDatetime")
        if station_id is None or tm is None:
            self.log.warning("weather.missing_keys", item=item)
            return None
        return {
            "station_id": int(station_id),
            "observed_at": parse_kma_hourly_timestamp(tm),
            "temperature_c": to_float(item.get("ta")),
            "precipitation_mm": to_float(item.get("rn")),
            "wind_speed_ms": to_float(item.get("ws")),
            "wind_direction_deg": to_float(item.get("wd")),
            "humidity_pct": to_float(item.get("hm")),
            "pressure_hpa": to_float(item.get("pa") or item.get("ps")),
        }
