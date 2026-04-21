from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import TYPE_CHECKING

from plain.exceptions import ImproperlyConfigured
from plain.postgres.database_url import DatabaseConfig, parse_database_url
from plain.runtime import settings as plain_settings

if TYPE_CHECKING:
    from plain.postgres.connection import DatabaseConnection


# Module-level ContextVar for per-task/per-thread connection storage.
# Each asyncio.Task gets its own copy (since Python 3.7.1).
# Thread pool threads maintain their own native context across work items,
# so connections persist across requests (honoring CONN_MAX_AGE).
_db_conn: ContextVar[DatabaseConnection | None] = ContextVar("_db_conn", default=None)


def _configure_settings() -> DatabaseConfig:
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

    parsed = parse_database_url(url)

    return {
        "DATABASE": parsed.get("DATABASE", ""),
        "USER": parsed.get("USER", ""),
        "PASSWORD": parsed.get("PASSWORD", ""),
        "HOST": parsed.get("HOST", ""),
        "PORT": parsed.get("PORT"),
        "CONN_MAX_AGE": plain_settings.POSTGRES_CONN_MAX_AGE,
        "CONN_HEALTH_CHECKS": plain_settings.POSTGRES_CONN_HEALTH_CHECKS,
        "OPTIONS": parsed.get("OPTIONS", {}),
        "TIME_ZONE": plain_settings.POSTGRES_TIME_ZONE,
        "TEST": {"DATABASE": None},
    }


def _create_connection() -> DatabaseConnection:
    from plain.postgres.connection import DatabaseConnection

    database_config = _configure_settings()
    return DatabaseConnection(database_config)


def get_connection() -> DatabaseConnection:
    """Get or create the database connection for the current context."""
    conn = _db_conn.get()
    if conn is None:
        conn = _create_connection()
        _db_conn.set(conn)
    return conn


def has_connection() -> bool:
    """Check if a database connection exists in the current context."""
    return _db_conn.get() is not None


@contextmanager
def read_only() -> Generator[None]:
    """Set the current database connection to read-only for the duration of this block.

    Any INSERT/UPDATE/DELETE/DDL will raise a database error. This applies
    to all queries in the block — both explicit transactions and implicit
    autocommit queries.
    """
    conn = get_connection()
    conn.set_read_only(True)
    try:
        yield
    finally:
        try:
            conn.set_read_only(False)
        except Exception:
            pass
