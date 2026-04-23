"""Where `DatabaseConnection` gets its psycopg connection — direct per-use
(`DirectSource`) or checkout/return against a shared pool (`PoolSource`).
The wrapper calls `source.acquire()` / `source.release()` / `source.config`
and is otherwise source-agnostic."""

from __future__ import annotations

import threading
import time
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

import psycopg
from psycopg_pool import ConnectionPool, PoolTimeout

from plain.exceptions import ImproperlyConfigured
from plain.logs import get_framework_logger
from plain.postgres.adapters import get_adapters_template
from plain.postgres.database_url import DatabaseConfig, parse_database_url
from plain.postgres.dialect import MAX_NAME_LENGTH
from plain.postgres.otel import (
    record_connection_acquire,
    record_connection_release,
    record_connection_timeout,
)
from plain.runtime import settings as plain_settings

logger = get_framework_logger()

if TYPE_CHECKING:
    from psycopg import Connection as PsycopgConnection


def build_connection_params(config: DatabaseConfig) -> dict[str, Any]:
    """Return kwargs suitable for `psycopg.connect()` from a `DatabaseConfig`.

    Every psycopg connection Plain opens — pooled or direct — goes through
    this function so they all share the same adapters, cursor factory, and
    validation rules.
    """
    options = config.get("OPTIONS", {})
    db_name = config["DATABASE"]
    if len(db_name) > MAX_NAME_LENGTH:
        raise ImproperlyConfigured(
            f"The database name {db_name!r} ({len(db_name)} characters) is longer "
            f"than PostgreSQL's limit of {MAX_NAME_LENGTH} characters. Supply a "
            "shorter database name in POSTGRES_URL."
        )
    conn_params: dict[str, Any] = {"dbname": db_name, **options}
    if config.get("USER"):
        conn_params["user"] = config["USER"]
    if config.get("PASSWORD"):
        conn_params["password"] = config["PASSWORD"]
    if config.get("HOST"):
        conn_params["host"] = config["HOST"]
    if config.get("PORT"):
        conn_params["port"] = config["PORT"]
    conn_params["context"] = get_adapters_template()
    # ClientCursor does client-side parameter binding and issues no
    # server-side prepared statements — safe behind transaction-mode
    # poolers like pgbouncer.
    conn_params["cursor_factory"] = psycopg.ClientCursor
    conn_params["prepare_threshold"] = conn_params.pop("prepare_threshold", None)
    return conn_params


class ConnectionSource(ABC):
    @property
    @abstractmethod
    def config(self) -> DatabaseConfig:
        """What server this source connects to. Read by otel, psql helper, maintenance."""

    @abstractmethod
    def acquire(self) -> PsycopgConnection[Any]: ...

    @abstractmethod
    def release(self, conn: PsycopgConnection[Any]) -> None: ...


class DirectSource(ConnectionSource):
    """Opens a fresh psycopg connection per acquire; closes on release."""

    def __init__(self, config: DatabaseConfig):
        self._config = config
        self._params = build_connection_params(config)

    @property
    def config(self) -> DatabaseConfig:
        return self._config

    def acquire(self) -> PsycopgConnection[Any]:
        return psycopg.connect(**self._params)

    def release(self, conn: PsycopgConnection[Any]) -> None:
        conn.close()


class PoolSource(ConnectionSource):
    """Lazily-opened `psycopg_pool.ConnectionPool`. `close()` drops the pool
    so the next acquire rebuilds against current settings.

    The `name` is used as the `db.client.connection.pool.name` attribute on
    the `db.client.connection.*` OpenTelemetry metric family.
    """

    def __init__(self, name: str = "runtime") -> None:
        self.name = name
        self._pool: ConnectionPool | None = None
        self._config: DatabaseConfig | None = None
        self._lock = threading.Lock()

    @property
    def config(self) -> DatabaseConfig:
        if self._config is None:
            # Opening the pool populates _config as a side effect; until then,
            # parse lazily so callers that only need config (otel on a no-op
            # request) don't force the pool open.
            self._config = _parse_runtime_url()
        return self._config

    def acquire(self) -> PsycopgConnection[Any]:
        pool = self._get_pool()
        start = time.perf_counter()
        try:
            conn = pool.getconn()
        except PoolTimeout:
            record_connection_timeout(self.name)
            raise
        checkout_time = time.perf_counter()
        record_connection_acquire(self.name, conn, checkout_time - start, checkout_time)
        return conn

    def release(self, conn: PsycopgConnection[Any]) -> None:
        record_connection_release(self.name, conn, time.perf_counter())
        pool = self._pool
        if pool is None:
            conn.close()
            return
        try:
            pool.putconn(conn)
        except Exception:
            logger.debug("Error returning connection to pool", exc_info=True)
            conn.close()

    def get_stats(self) -> dict[str, int] | None:
        """Return pool statistics, or None if the pool is closed."""
        pool = self._pool
        if pool is None:
            return None
        try:
            return pool.get_stats()
        except Exception:
            return None

    def close(self, timeout: float = 5.0) -> None:
        with self._lock:
            self._config = None
            if self._pool is not None:
                try:
                    self._pool.close(timeout=timeout)
                finally:
                    self._pool = None

    def _get_pool(self) -> ConnectionPool:
        if self._pool is None:
            with self._lock:
                if self._pool is None:
                    self._pool = self._open_pool()
        return self._pool

    def _open_pool(self) -> ConnectionPool:
        self._config = _parse_runtime_url()
        params = build_connection_params(self._config)
        pool = ConnectionPool(
            kwargs=params,
            open=False,
            reset=_reset_pooled_connection,
            min_size=plain_settings.POSTGRES_POOL_MIN_SIZE,
            max_size=plain_settings.POSTGRES_POOL_MAX_SIZE,
            max_lifetime=plain_settings.POSTGRES_POOL_MAX_LIFETIME,
            timeout=plain_settings.POSTGRES_POOL_TIMEOUT,
        )
        pool.open(wait=False)
        return pool


def _parse_runtime_url() -> DatabaseConfig:
    """Validate `POSTGRES_URL` and return its parsed config.

    Raises `ImproperlyConfigured` with a friendly message when the URL is
    empty or explicitly disabled, so callers that only need the config (like
    `plain postgres shell`) don't fall through to a raw `ValueError`.
    """
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
    return parse_database_url(url)


def _reset_pooled_connection(conn: PsycopgConnection[Any]) -> None:
    """Ensure a connection is clean before returning to the pool.

    Rolls back any in-progress transaction and restores autocommit=True so
    the next checkout starts in a known state. Raising here signals the pool
    to discard the connection.
    """
    if not conn.autocommit:
        conn.rollback()
        conn.autocommit = True


# Process-wide singleton. Pool is lazy-opened on first acquire.
runtime_pool_source = PoolSource(name="runtime")
