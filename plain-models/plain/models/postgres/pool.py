from __future__ import annotations

import datetime
import logging
import threading
import zoneinfo
from typing import TYPE_CHECKING, Any

from psycopg import IsolationLevel
from psycopg import sql as psycopg_sql
from psycopg_pool import ConnectionPool

from plain.exceptions import ImproperlyConfigured
from plain.runtime import settings

if TYPE_CHECKING:
    from plain.models.connections import DatabaseConfig

logger = logging.getLogger("plain.models.postgres")


def _build_connection_params(
    config: DatabaseConfig,
    tz: datetime.tzinfo,
    *,
    autocommit: bool = False,
) -> dict[str, Any]:
    """Build psycopg connection kwargs from a DatabaseConfig."""
    from .connection import get_adapters_template

    options = config.get("OPTIONS", {})
    db_name = config.get("DATABASE")
    if db_name is None:
        db_name = "postgres"

    conn_params: dict[str, Any] = {
        "dbname": db_name,
        **options,
    }
    if autocommit:
        conn_params["autocommit"] = True

    conn_params.pop("assume_role", None)
    conn_params.pop("isolation_level", None)
    conn_params.pop("server_side_binding", None)
    if config["USER"]:
        conn_params["user"] = config["USER"]
    if config["PASSWORD"]:
        conn_params["password"] = config["PASSWORD"]
    if config["HOST"]:
        conn_params["host"] = config["HOST"]
    if config["PORT"]:
        conn_params["port"] = config["PORT"]
    conn_params["context"] = get_adapters_template(tz)
    conn_params["prepare_threshold"] = conn_params.pop("prepare_threshold", None)
    return conn_params


def _configure_connection_timezone(conn: Any, tz_name: str | None) -> None:
    """Set timezone on a connection if it differs from current."""
    if not tz_name:
        return
    conn_tz = conn.info.parameter_status("TimeZone")
    if conn_tz != tz_name:
        conn.execute("SELECT set_config('TimeZone', %s, false)", [tz_name])


def _configure_connection_role(conn: Any, options: dict[str, Any]) -> None:
    """Set role on a connection if assume_role is configured."""
    if new_role := options.get("assume_role"):
        conn.execute(
            psycopg_sql.SQL("SET ROLE {}").format(psycopg_sql.Identifier(new_role))
        )


def _resolve_isolation_level(options: dict[str, Any]) -> IsolationLevel | None:
    """Resolve isolation level from OPTIONS, returning None if not configured."""
    if "isolation_level" not in options:
        return None
    try:
        return IsolationLevel(options["isolation_level"])
    except ValueError:
        raise ImproperlyConfigured(
            f"Invalid transaction isolation level {options['isolation_level']} "
            f"specified. Use one of the psycopg.IsolationLevel values."
        )


class PostgresPool:
    """Process-level connection pool for PostgreSQL.

    All threads share this pool of physical connections.  Per-thread state
    (transactions, savepoints, autocommit) lives in the DatabaseConnection
    wrapper stored in a ContextVar — see connections.py.
    """

    _pool: ConnectionPool | None = None
    _lock = threading.Lock()

    @classmethod
    def get_pool(cls) -> ConnectionPool:
        """Lazily create and return the connection pool."""
        if cls._pool is not None:
            return cls._pool

        with cls._lock:
            # Double-check after acquiring the lock.
            if cls._pool is not None:
                return cls._pool

            from plain.models.connections import _configure_settings

            from .connection import Cursor, ServerBindingCursor

            config = _configure_settings()

            tz_name = config.get("TIME_ZONE")
            if tz_name is None:
                tz = datetime.UTC
            else:
                tz = zoneinfo.ZoneInfo(tz_name)

            conn_kwargs = _build_connection_params(config, tz, autocommit=True)
            options = config.get("OPTIONS", {})

            # Set cursor factory — matches get_new_connection() behavior.
            conn_kwargs["cursor_factory"] = (
                ServerBindingCursor
                if options.get("server_side_binding") is True
                else Cursor
            )

            isolation_level = _resolve_isolation_level(options)

            def configure(conn: Any) -> None:
                """Configure a new pooled connection (timezone, role, isolation level)."""
                _configure_connection_timezone(conn, tz_name)
                _configure_connection_role(conn, options)
                if isolation_level is not None:
                    conn.isolation_level = isolation_level

            def reset(conn: Any) -> None:
                """Reset a connection to clean state when returned to pool."""
                conn.rollback()
                conn.autocommit = True

            pool_kwargs = settings.POSTGRES_POOL.copy()
            # Remove keys that would conflict with internally managed pool config.
            for key in (
                "conninfo",
                "connection_class",
                "kwargs",
                "open",
                "configure",
                "reset",
                "check",
            ):
                pool_kwargs.pop(key, None)

            pool = ConnectionPool(
                kwargs=conn_kwargs,
                open=False,
                configure=configure,
                reset=reset,
                check=ConnectionPool.check_connection,
                **pool_kwargs,
            )
            # Open the pool without waiting — min_size connections are created
            # in the background while the first getconn() proceeds immediately.
            pool.open(wait=False)
            cls._pool = pool

        return cls._pool

    @classmethod
    def return_connection(cls, conn: Any) -> None:
        """Return a connection to the pool, or close it directly if the pool has changed."""
        pool = cls._pool  # Snapshot to avoid TOCTOU
        if pool is not None:
            try:
                pool.putconn(conn)
                return
            except ValueError:
                # Connection belongs to a previous pool — close directly.
                logger.debug("Connection belongs to a previous pool, closing directly")
        conn.close()

    @classmethod
    def close(cls) -> None:
        """Close and discard the connection pool."""
        with cls._lock:
            if cls._pool is not None:
                cls._pool.close(timeout=5)
                cls._pool = None
