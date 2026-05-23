"""`ps-dr-ingest` — load a downloaded DR transaction file (D5/D6) into the DB.

Two intake modes:
  - --file path/to.csv   : ingest a local file
  - --url <download_url> : fetch from a URL (also stored as raw)
"""
from __future__ import annotations

from pathlib import Path

import click

from src.collectors.dr_history import DrEconomicCollector, DrReliabilityCollector
from src.logging_setup import configure_logging, get_logger
from src.storage.db import init_db


@click.command()
@click.option(
    "--type",
    "dr_type",
    type=click.Choice(["economic", "reliability"]),
    required=True,
    help="DR program type (economic = D5, reliability = D6)",
)
@click.option(
    "--file",
    "file_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=None,
    help="Local CSV/XLSX path",
)
@click.option(
    "--url",
    type=str,
    default=None,
    help="Override download URL (otherwise uses config.datasets.yaml)",
)
def main(dr_type: str, file_path: Path | None, url: str | None) -> None:
    if not file_path and not url:
        raise click.UsageError("Provide either --file or --url")
    configure_logging()
    log = get_logger(__name__)
    init_db()

    collector_cls = DrEconomicCollector if dr_type == "economic" else DrReliabilityCollector
    collector = collector_cls()
    if file_path:
        n = collector.ingest_file(file_path)
        log.info("dr.ingest_file.done", type=dr_type, path=str(file_path), rows=n)
    else:
        n = collector.ingest_url(url)
        log.info("dr.ingest_url.done", type=dr_type, url=url, rows=n)


if __name__ == "__main__":
    main()
