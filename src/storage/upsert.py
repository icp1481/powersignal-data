"""Idempotent upsert helpers.

We use SQLAlchemy Core's dialect-aware insert: SQLite -> `INSERT OR REPLACE` via
`sqlite.insert(...).on_conflict_do_update`; Postgres -> `INSERT ... ON CONFLICT`.
Both share the same call signature.
"""
from __future__ import annotations

from typing import Any, Iterable

from sqlalchemy import inspect
from sqlalchemy.orm import Session

from src.storage.models import Base


def upsert_many(
    session: Session,
    model: type[Base],
    rows: Iterable[dict[str, Any]],
    *,
    conflict_cols: list[str],
) -> tuple[int, int]:
    """Insert-or-update many rows. Returns (attempted, count) — actual
    insert/update split isn't easily knowable on SQLite, so we just return the
    total attempted count for both fields.

    Caller is responsible for committing the session.
    """
    rows = list(rows)
    if not rows:
        return (0, 0)
    bind = session.get_bind()
    dialect = bind.dialect.name

    if dialect == "sqlite":
        from sqlalchemy.dialects.sqlite import insert as sqlite_insert

        stmt = sqlite_insert(model.__table__)
        update_cols = {
            c.name: stmt.excluded[c.name]
            for c in model.__table__.columns
            if c.name not in conflict_cols and c.name != _pk_name(model)
        }
        stmt = stmt.on_conflict_do_update(
            index_elements=conflict_cols, set_=update_cols
        )
        session.execute(stmt, rows)
        return (len(rows), len(rows))

    if dialect == "postgresql":
        from sqlalchemy.dialects.postgresql import insert as pg_insert

        stmt = pg_insert(model.__table__)
        update_cols = {
            c.name: stmt.excluded[c.name]
            for c in model.__table__.columns
            if c.name not in conflict_cols and c.name != _pk_name(model)
        }
        stmt = stmt.on_conflict_do_update(
            index_elements=conflict_cols, set_=update_cols
        )
        session.execute(stmt, rows)
        return (len(rows), len(rows))

    # Fallback: naive insert-then-update — caller's table must tolerate it.
    raise NotImplementedError(f"upsert_many not implemented for dialect {dialect!r}")


def _pk_name(model: type[Base]) -> str:
    pks = inspect(model).primary_key
    return pks[0].name if pks else ""
