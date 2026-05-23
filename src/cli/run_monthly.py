"""`ps-monthly` — pull monthly-cadence datasets (D4 LNG fuel cost)."""
from __future__ import annotations

import click

from src.collectors.lng import FuelCostCollector
from src.logging_setup import configure_logging, get_logger
from src.storage.db import init_db


@click.command()
@click.option("--lng/--no-lng", default=True, help="Run D4 fuel cost collector")
def main(lng: bool) -> None:
    configure_logging()
    log = get_logger(__name__)
    init_db()
    if lng:
        with FuelCostCollector() as c:
            n = c.run()
            log.info("monthly.lng.done", rows=n)


if __name__ == "__main__":
    main()
