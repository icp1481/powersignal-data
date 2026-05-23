"""`ps-daily` — pull all daily-cadence datasets (D1 SMP, D2 supply, D3 weather).

Intended to be run on a 23:30 KST cron. D2 is a snapshot — run separately on a
shorter cron if you need fresher real-time data.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

import click

from src.collectors.smp import SmpCollector
from src.collectors.supply import SupplyCollector
from src.collectors.weather import WeatherCollector
from src.logging_setup import configure_logging, get_logger
from src.storage.db import init_db


@click.command()
@click.option("--smp/--no-smp", default=True, help="Run D1 SMP collector")
@click.option("--supply/--no-supply", default=True, help="Run D2 supply snapshot collector")
@click.option("--weather/--no-weather", default=True, help="Run D3 weather collector")
@click.option(
    "--weather-date",
    type=click.DateTime(formats=["%Y-%m-%d"]),
    default=None,
    help="ASOS observation date (default: yesterday). Single day only.",
)
@click.option(
    "--stations",
    type=str,
    default=None,
    help="Comma-separated KMA station IDs to override defaults",
)
def main(smp: bool, supply: bool, weather: bool, weather_date, stations: str | None) -> None:
    configure_logging()
    log = get_logger(__name__)
    init_db()

    if smp:
        with SmpCollector() as c:
            n = c.run()
            log.info("daily.smp.done", rows=n)

    if supply:
        with SupplyCollector() as c:
            n = c.run()
            log.info("daily.supply.done", rows=n)

    if weather:
        target: date = (
            weather_date.date() if isinstance(weather_date, datetime) else (
                datetime.utcnow().date() - timedelta(days=1)
            )
        )
        station_ids = (
            [int(s.strip()) for s in stations.split(",") if s.strip()] if stations else None
        )
        with WeatherCollector() as c:
            n = c.run(start_date=target, end_date=target, stations=station_ids)
            log.info("daily.weather.done", rows=n, date=str(target))


if __name__ == "__main__":
    main()
