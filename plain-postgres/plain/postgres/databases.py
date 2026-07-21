"""Cluster-level database management — CREATE/DROP DATABASE and friends.

Everything else in `plain.postgres` operates *inside* the database that
`POSTGRES_URL` points at. This module is the exception: it operates on the
cluster, which means it needs a role with `CREATEDB` and a connection to the
`postgres` maintenance database.

That makes it a **development and test** capability, not a production one —
most managed Postgres providers hand your app a role that owns exactly one
database and cannot create more. Nothing on the runtime path imports this
module, and `tests/internal/test_databases_not_on_runtime_path.py` enforces
that.

This module provides mechanism only. Policy — whether to prompt before
clobbering, how to name databases, what to store in a comment, when to fork
via `TEMPLATE` versus `pg_dump` — belongs to the caller.
"""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass

import psycopg
from psycopg import sql

from plain.postgres.database_url import DatabaseConfig
from plain.postgres.sources import build_connection_params

__all__ = [
    "DatabaseInfo",
    "connection_count",
    "create_database",
    "database_exists",
    "drop_database",
    "get_database_comment",
    "list_databases",
    "maintenance_cursor",
    "set_database_comment",
    "terminate_connections",
]


@dataclass(frozen=True)
class DatabaseInfo:
    """A row from `list_databases()`."""

    name: str
    comment: str | None
    size_bytes: int


@contextmanager
def maintenance_cursor(config: DatabaseConfig) -> Generator[psycopg.Cursor]:
    """Yield a cursor on the `postgres` maintenance database.

    CREATE DATABASE / DROP DATABASE can't run against the target database
    itself and can't run inside a transaction — so connect to `postgres`
    with autocommit and use a raw psycopg cursor (no wrapper machinery,
    no pool).
    """
    maintenance_config: DatabaseConfig = {**config, "DATABASE": "postgres"}
    params = build_connection_params(maintenance_config)
    with psycopg.connect(**params, autocommit=True) as conn:
        with conn.cursor() as cursor:
            yield cursor


def create_database(
    config: DatabaseConfig, *, name: str, template: str | None = None
) -> None:
    """CREATE DATABASE, optionally copying an existing one via TEMPLATE.

    `TEMPLATE` is a file-level copy, so it's near-instant regardless of data
    size — but Postgres requires the template database to have no other
    connections. Call `terminate_connections()` first, or fall back to
    dump/restore, if the source may be in use.

    Raises `psycopg.errors.DuplicateDatabase` if `name` already exists.
    """
    if template:
        statement = sql.SQL("CREATE DATABASE {} TEMPLATE {}").format(
            sql.Identifier(name), sql.Identifier(template)
        )
    else:
        statement = sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name))

    with maintenance_cursor(config) as cursor:
        cursor.execute(statement)


def drop_database(config: DatabaseConfig, *, name: str, force: bool = False) -> None:
    """DROP DATABASE IF EXISTS.

    `force` adds `WITH (FORCE)`, which terminates other connections to the
    database instead of failing.
    """
    if force:
        statement = sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(
            sql.Identifier(name)
        )
    else:
        statement = sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(name))

    with maintenance_cursor(config) as cursor:
        cursor.execute(statement)


def database_exists(config: DatabaseConfig, *, name: str) -> bool:
    with maintenance_cursor(config) as cursor:
        cursor.execute("SELECT 1 FROM pg_database WHERE datname = %s", [name])
        return cursor.fetchone() is not None


def list_databases(config: DatabaseConfig, *, prefix: str = "") -> list[DatabaseInfo]:
    """List databases whose name starts with `prefix`, ordered by name."""
    with maintenance_cursor(config) as cursor:
        cursor.execute(
            "SELECT datname, shobj_description(oid, 'pg_database'), "
            "pg_database_size(datname) "
            "FROM pg_database WHERE datname LIKE %s ORDER BY datname",
            [prefix + "%"],
        )
        rows = cursor.fetchall()

    return [
        DatabaseInfo(name=name, comment=comment, size_bytes=size)
        for name, comment, size in rows
    ]


def get_database_comment(config: DatabaseConfig, *, name: str) -> str | None:
    """Return the database's COMMENT as raw text, or None if unset.

    Callers that store structured data are responsible for their own encoding.
    """
    with maintenance_cursor(config) as cursor:
        cursor.execute(
            "SELECT shobj_description(oid, 'pg_database') "
            "FROM pg_database WHERE datname = %s",
            [name],
        )
        row = cursor.fetchone()

    return row[0] if row else None


def set_database_comment(config: DatabaseConfig, *, name: str, comment: str) -> None:
    """Set the database's COMMENT to raw text."""
    with maintenance_cursor(config) as cursor:
        cursor.execute(
            sql.SQL("COMMENT ON DATABASE {} IS {}").format(
                sql.Identifier(name), sql.Literal(comment)
            )
        )


def connection_count(config: DatabaseConfig, *, name: str) -> int:
    """Count backends currently connected to `name`, excluding our own."""
    with maintenance_cursor(config) as cursor:
        cursor.execute(
            "SELECT count(*) FROM pg_stat_activity "
            "WHERE datname = %s AND pid <> pg_backend_pid()",
            [name],
        )
        row = cursor.fetchone()
        return row[0] if row else 0


def terminate_connections(config: DatabaseConfig, *, name: str) -> None:
    """Terminate every other backend connected to `name`.

    Needed before `CREATE DATABASE … TEMPLATE`, which requires the source to
    be idle.
    """
    with maintenance_cursor(config) as cursor:
        cursor.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            "WHERE datname = %s AND pid <> pg_backend_pid()",
            [name],
        )
