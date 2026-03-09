from __future__ import annotations

from contextvars import ContextVar
from typing import TYPE_CHECKING, Any, TypedDict

from plain.exceptions import ImproperlyConfigured
from plain.runtime import settings as plain_settings

if TYPE_CHECKING:
    from plain.models.postgres.connection import DatabaseConnection


class DatabaseConfig(TypedDict, total=False):
    HOST: str
    DATABASE: str | None
    OPTIONS: dict[str, Any]
    PASSWORD: str
    PORT: int | None
    TEST: dict[str, Any]
    TIME_ZONE: str | None
    USER: str


# Module-level ContextVar for per-task/per-thread connection storage.
# Each asyncio.Task gets its own copy (since Python 3.7.1).
# Thread pool threads maintain their own native context across work items,
# so the wrapper persists across requests. Between requests, the wrapper's
# connection is returned to the pool (connection=None) and re-checked out
# on next use.
_db_conn: ContextVar[DatabaseConnection | None] = ContextVar("_db_conn", default=None)


def _configure_settings() -> DatabaseConfig:
    if plain_settings.POSTGRES_DATABASE == "":
        raise ImproperlyConfigured(
            "The PostgreSQL database has been disabled (DATABASE_URL=none). "
            "No database operations are available in this context."
        )
    if not plain_settings.POSTGRES_DATABASE:  # None or unresolved setting
        raise ImproperlyConfigured(
            "PostgreSQL database is not configured. "
            "Set DATABASE_URL or the individual POSTGRES_* settings."
        )

    return {
        "DATABASE": plain_settings.POSTGRES_DATABASE,
        "USER": plain_settings.POSTGRES_USER,
        "PASSWORD": plain_settings.POSTGRES_PASSWORD,
        "HOST": plain_settings.POSTGRES_HOST,
        "PORT": plain_settings.POSTGRES_PORT,
        "OPTIONS": plain_settings.POSTGRES_OPTIONS,
        "TIME_ZONE": plain_settings.POSTGRES_TIME_ZONE,
        "TEST": {"DATABASE": None},
    }


def _create_connection() -> DatabaseConnection:
    from plain.models.postgres.connection import DatabaseConnection

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


def return_connection() -> None:
    """Return the current context's connection to the pool."""
    conn = _db_conn.get()
    if conn is not None and conn.connection is not None:
        conn.close()


def close_pool() -> None:
    """Close and discard the connection pool (for test DB switching)."""
    from plain.models.postgres.pool import PostgresPool

    PostgresPool.close()
