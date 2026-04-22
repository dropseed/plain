from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import TYPE_CHECKING

from plain.exceptions import ImproperlyConfigured
from plain.logs import get_framework_logger
from plain.postgres.database_url import parse_database_url
from plain.runtime import settings as plain_settings

if TYPE_CHECKING:
    from plain.postgres.connection import DatabaseConnection


logger = get_framework_logger()


# Module-level ContextVar for per-task/per-thread connection storage.
# Each asyncio.Task gets its own copy (since Python 3.7.1).
# Thread pool threads maintain their own native context across work items,
# so connections persist across requests (honoring CONN_MAX_AGE).
_db_conn: ContextVar[DatabaseConnection | None] = ContextVar("_db_conn", default=None)


def get_connection() -> DatabaseConnection:
    """Get or create the database connection for the current context."""
    from plain.postgres.connection import DatabaseConnection

    conn = _db_conn.get()
    if conn is None:
        url = str(plain_settings.POSTGRES_URL)
        if not url:
            raise ImproperlyConfigured(
                "PostgreSQL database is not configured. "
                "Set POSTGRES_URL (or DATABASE_URL) to a postgres://... connection string."
            )
        if url.lower() == "none":
            raise ImproperlyConfigured(
                "The PostgreSQL database has been disabled (POSTGRES_URL=none). "
                "No database operations are available in this context."
            )
        conn = DatabaseConnection.from_url(url)
        _db_conn.set(conn)
    return conn


def has_connection() -> bool:
    """Check if a database connection exists in the current context."""
    return _db_conn.get() is not None


@contextmanager
def use_management_connection() -> Generator[DatabaseConnection]:
    """Replace the active connection with one opened against POSTGRES_MANAGEMENT_URL.

    Inside the block, `get_connection()` returns a fresh connection opened
    against `POSTGRES_MANAGEMENT_URL` (falling back to `POSTGRES_URL` if the
    management URL is empty). On exit, the management connection is closed
    and the prior connection (if any) is restored.

    Use this to route migrations, convergence, and other DDL through a
    separate connection — e.g. a direct Postgres port when the runtime
    connection goes through a transaction-mode pgbouncer, or a DDL-capable
    role when the runtime role only has DML.
    """
    from plain.postgres.connection import DatabaseConnection

    management_url = str(plain_settings.POSTGRES_MANAGEMENT_URL)
    runtime_url = str(plain_settings.POSTGRES_URL)

    # When no distinct management URL is configured, reuse the active
    # connection so any outer transaction, session state, temp tables, or
    # advisory locks are preserved — the block becomes a no-op connection-wise.
    if not management_url or management_url == runtime_url:
        yield get_connection()
        return

    if management_url.lower() == "none":
        raise ImproperlyConfigured(
            "The PostgreSQL database has been disabled (POSTGRES_MANAGEMENT_URL=none). "
            "No database operations are available in this context."
        )

    parsed = parse_database_url(management_url)
    logger.info(
        "Using management database connection",
        extra={
            "context": {
                "host": parsed.get("HOST", ""),
                "port": parsed.get("PORT"),
                "database": parsed.get("DATABASE", ""),
            }
        },
    )

    new_conn = DatabaseConnection.from_url(management_url)
    token = _db_conn.set(new_conn)
    try:
        yield new_conn
    finally:
        try:
            new_conn.close()
        except Exception:
            logger.debug("Error closing management connection", exc_info=True)
        _db_conn.reset(token)


@contextmanager
def read_only() -> Generator[None]:
    """Run a block of code inside a read-only transaction.

    Opens a single ``BEGIN READ ONLY`` transaction for the duration of the
    block — any INSERT/UPDATE/DELETE/DDL raises
    ``psycopg.errors.ReadOnlySqlTransaction``. Nested ``atomic()`` blocks
    inside become savepoints of the outer read-only transaction and inherit
    read-only.

    Because this opens its own transaction, it cannot be entered while an
    ``atomic()`` block is already active.
    """
    from plain.postgres.transaction import (
        TransactionManagementError,
        atomic,
    )

    conn = get_connection()
    if conn.in_atomic_block:
        raise TransactionManagementError(
            "read_only() cannot be entered inside an existing atomic() block; "
            "it opens its own transaction."
        )
    conn.ensure_connection()
    psy_conn = conn.connection
    assert psy_conn is not None
    # psycopg lazily emits BEGIN on the first query once autocommit is off;
    # setting read_only=True makes it a READ ONLY transaction.
    psy_conn.read_only = True
    try:
        with atomic():
            yield
    finally:
        try:
            psy_conn.read_only = None
        except Exception:
            logger.debug("Error clearing read_only on connection", exc_info=True)
