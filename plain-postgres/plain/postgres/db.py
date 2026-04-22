"""Public database API: the active-connection ContextVar plus management
and read-only helpers. Per-request lifecycle (clearing the query log,
returning pooled connections) lives in `DatabaseConnectionMiddleware`."""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import TYPE_CHECKING

from plain.exceptions import ImproperlyConfigured
from plain.logs import get_framework_logger
from plain.postgres.database_url import parse_database_url
from plain.postgres.sources import DirectSource, runtime_pool_source
from plain.runtime import settings as plain_settings

if TYPE_CHECKING:
    from plain.postgres.connection import DatabaseConnection

logger = get_framework_logger()

PLAIN_VERSION_PICKLE_KEY = "_plain_version"


_db_conn: ContextVar[DatabaseConnection | None] = ContextVar("_db_conn", default=None)


def get_connection() -> DatabaseConnection:
    from plain.postgres.connection import DatabaseConnection

    conn = _db_conn.get()
    if conn is None:
        conn = DatabaseConnection(runtime_pool_source)
        _db_conn.set(conn)
    return conn


def has_connection() -> bool:
    return _db_conn.get() is not None


def return_database_connection(conn: DatabaseConnection | None = None) -> None:
    """Return a psycopg connection, clearing its queries log along the way.

    Pool-backed wrappers return to the pool; direct-backed wrappers close.
    The wrapper itself stays referenced by the caller (typically a
    ContextVar) and will acquire a fresh connection on next use.

    Pass `conn` explicitly when the caller is running outside the
    context that owns the wrapper — e.g. a streaming response's resource
    closer runs after `handle()` returns, so the request `ContextVar`
    context is no longer active. Middleware captures the wrapper at
    response time and hands it in. Without `conn`, falls back to
    `_db_conn.get()` for callers that *are* still in-context.

    No-op when a transaction is in progress — returning mid-transaction
    would roll back the caller's work (tests wrap each case in `atomic()`,
    streaming views may still be mid-query).
    """
    if conn is None:
        conn = _db_conn.get()
    if conn is None:
        return
    if conn.in_atomic_block:
        return
    conn.queries_log.clear()
    conn.close()


@contextmanager
def use_management_connection() -> Generator[DatabaseConnection]:
    """Swap in a direct connection against `POSTGRES_MANAGEMENT_URL` for this block.

    Used to route migrations, convergence, and other DDL through a separate
    connection — e.g. a direct Postgres port when the runtime connection
    goes through a transaction-mode pgbouncer, or a DDL-capable role when
    the runtime role only has DML. Falls back to the active connection when
    the management URL is unset or equals `POSTGRES_URL` — preserves any
    outer transaction, session state, temp tables, or advisory locks.
    """
    from plain.postgres.connection import DatabaseConnection

    management_url = str(plain_settings.POSTGRES_MANAGEMENT_URL)
    runtime_url = str(plain_settings.POSTGRES_URL)

    if not management_url or management_url == runtime_url:
        yield get_connection()
        return

    if management_url.lower() == "none":
        raise ImproperlyConfigured(
            "The PostgreSQL database has been disabled (POSTGRES_MANAGEMENT_URL=none). "
            "No database operations are available in this context."
        )

    config = parse_database_url(management_url)
    logger.info(
        "Using management database connection",
        extra={
            "context": {
                "host": config["HOST"],
                "port": config["PORT"],
                "database": config["DATABASE"],
            }
        },
    )

    new_conn = DatabaseConnection(DirectSource(config))
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
