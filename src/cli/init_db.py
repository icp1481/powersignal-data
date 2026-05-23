"""`ps-init-db` — create all tables. Idempotent."""
from __future__ import annotations

import click

from src.logging_setup import configure_logging, get_logger
from src.storage.db import init_db


@click.command()
def main() -> None:
    configure_logging()
    log = get_logger(__name__)
    init_db()
    log.info("db.initialized")


if __name__ == "__main__":
    main()
