"""How far apart are this database's schema and this checkout's code?

Two directions, and they mean very different things:

- **behind** — migrations on disk the database hasn't applied. Self-correcting;
  `plain postgres sync` applies them on the next `plain dev`.
- **ahead** — migrations recorded in the database with no file on disk. Not
  self-correcting, and the usual cause is switching branches: you applied a
  migration on one branch, switched away, and the table is still there.
"""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from typing import Any


@contextmanager
def _connected(url: str) -> Generator[Any]:
    """Open `url` and install it as the active connection.

    The migration recorder reads applied rows through `Migration.query`, which
    uses the *global* connection rather than one passed in — so it has to be
    installed, the same way `use_test_database` does it.
    """
    from plain.postgres.connection import DatabaseConnection
    from plain.postgres.database_url import parse_database_url
    from plain.postgres.db import _db_conn
    from plain.postgres.sources import DirectSource

    conn = DatabaseConnection(DirectSource(parse_database_url(url)))
    token = _db_conn.set(conn)
    try:
        yield conn
    finally:
        _db_conn.reset(token)
        conn.close()


def pending_migration_count(url: str) -> int:
    """Migrations on disk that this database hasn't applied yet."""
    from plain.postgres.migrations.executor import MigrationExecutor

    with _connected(url) as conn:
        executor = MigrationExecutor(conn)
        return len(executor.migration_plan(executor.loader.graph.leaf_nodes()))


def migrations_not_on_disk(url: str) -> list[tuple[str, str]]:
    """Migrations this database has applied that no longer exist as files.

    This is the "your database is ahead of your code" signal. The same
    comparison backs the `postgres.prunable_migrations` preflight check, but
    the remedy differs by context: prune is right when a migration was deleted
    for good, and wrong when you simply switched branches and will switch back.
    """
    from plain.postgres.migrations.loader import MigrationLoader
    from plain.postgres.migrations.recorder import MigrationRecorder

    with _connected(url) as conn:
        loader = MigrationLoader(conn, ignore_no_migrations=True)
        applied = MigrationRecorder(conn).applied_migrations()
        on_disk = loader.disk_migrations or {}
        return sorted(m for m in applied if m not in on_disk)
