from __future__ import annotations

import os
import sys
from collections.abc import Generator
from contextlib import contextmanager

import psycopg
from psycopg import errors, sql

from plain.postgres.connection import DatabaseConnection
from plain.postgres.database_url import (
    DatabaseConfig,
    parse_database_url,
    replace_database_name,
)
from plain.postgres.db import _db_conn
from plain.postgres.dialect import MAX_NAME_LENGTH
from plain.postgres.migrations.executor import MigrationExecutor
from plain.postgres.sources import DirectSource, build_connection_params
from plain.postgres.utils import names_digest
from plain.runtime import settings

TEST_DATABASE_PREFIX = "test_"


def _log(msg: str) -> None:
    sys.stderr.write(msg + os.linesep)


def _compute_test_db_name(base_name: str, prefix: str = "") -> str:
    """Compute the test database name from the runtime DB name."""
    if prefix:
        name = f"{prefix}_{base_name}"
        if len(name) > MAX_NAME_LENGTH:
            hash_suffix = names_digest(name, length=8)
            name = name[: MAX_NAME_LENGTH - 9] + "_" + hash_suffix
        return name
    return TEST_DATABASE_PREFIX + base_name


@contextmanager
def _maintenance_cursor(config: DatabaseConfig) -> Generator[psycopg.Cursor]:
    """Yield a cursor on the `postgres` maintenance DB.

    CREATE DATABASE / DROP DATABASE can't run against the target database
    itself and can't run inside a transaction — so connect to `postgres`
    with autocommit and use a raw psycopg cursor (no wrapper machinery,
    no pool).
    """
    maint_config: DatabaseConfig = {**config, "DATABASE": "postgres"}
    params = build_connection_params(maint_config)
    with psycopg.connect(**params, autocommit=True) as conn:
        with conn.cursor() as cursor:
            yield cursor


def _create_database_on_server(
    config: DatabaseConfig, *, name: str, verbosity: int, autoclobber: bool
) -> None:
    """CREATE DATABASE via the maintenance connection, with autoclobber fallback."""
    ident = sql.Identifier(name)
    create = sql.SQL("CREATE DATABASE {}").format(ident)
    drop = sql.SQL("DROP DATABASE {}").format(ident)
    with _maintenance_cursor(config) as cursor:
        try:
            cursor.execute(create)
            return
        except errors.DuplicateDatabase as e:
            _log(f"Got an error creating the test database: {e}")
        except Exception as e:
            _log(f"Got an error creating the test database: {e}")
            sys.exit(2)

        if not autoclobber:
            confirm = input(
                "Type 'yes' if you would like to try deleting the test "
                f"database '{name}', or 'no' to cancel: "
            )
            if confirm != "yes":
                _log("Tests cancelled.")
                sys.exit(1)

        try:
            if verbosity >= 1:
                _log(f"Destroying old test database '{name}'...")
            cursor.execute(drop)
            cursor.execute(create)
        except Exception as e:
            _log(f"Got an error recreating the test database: {e}")
            sys.exit(2)


def _drop_database_on_server(config: DatabaseConfig, name: str) -> None:
    with _maintenance_cursor(config) as cursor:
        cursor.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(name)))


@contextmanager
def use_test_database(*, verbosity: int = 1, prefix: str = "") -> Generator[str]:
    """Create a test database, install it as the active connection, drop on exit.

    Inside the block, `get_connection()` returns a connection opened against
    the test database. Migrations and convergence run directly via their
    Python APIs (`MigrationExecutor`, `plan_convergence`) — not via the CLI
    commands — so no `POSTGRES_MANAGEMENT_URL` swap happens during setup.

    Yields the test database name.
    """
    from plain.postgres.convergence import execute_plan, plan_convergence

    runtime_url = str(settings.POSTGRES_URL)
    if not runtime_url:
        raise ValueError("POSTGRES_URL must be set before creating a test database.")

    base_name = parse_database_url(runtime_url).get("DATABASE")
    if not base_name:
        raise ValueError("POSTGRES_URL must include a database name")

    test_db_name = _compute_test_db_name(base_name, prefix)

    if verbosity >= 1:
        _log(f"Creating test database '{test_db_name}'...")

    test_url = replace_database_name(runtime_url, test_db_name)
    test_config = parse_database_url(test_url)
    test_conn = DatabaseConnection(DirectSource(test_config))

    # Create the test database on the server via a direct `postgres`-DB
    # connection — test_conn itself can't connect to a DB that doesn't
    # exist yet, so we open a sibling connection against `postgres`.
    _create_database_on_server(
        test_config, name=test_db_name, verbosity=verbosity, autoclobber=True
    )

    conn_token = _db_conn.set(test_conn)
    try:
        executor = MigrationExecutor(test_conn)
        targets = list(executor.loader.graph.leaf_nodes())
        executor.migrate(targets)

        plan = plan_convergence()
        result = execute_plan(plan.executable())
        if not result.ok:
            failed = [r for r in result.results if not r.ok]
            raise RuntimeError(
                f"Convergence failed during test DB setup: {failed[0].item.describe()} — {failed[0].error}"
            )
        # A fresh DB from migrations shouldn't have undeclared objects or
        # changed definitions — safety net so test setup follows sync policy.
        if plan.blocked:
            problem = plan.blocked[0]
            raise RuntimeError(
                f"Convergence blocked during test DB setup: {problem.describe()}"
            )

        test_conn.ensure_connection()

        yield test_db_name
    finally:
        _db_conn.reset(conn_token)

        try:
            test_conn.close()
        except Exception:
            pass

        if verbosity >= 1:
            _log(f"Destroying test database '{test_db_name}'...")
        try:
            _drop_database_on_server(test_config, test_db_name)
        except Exception as e:
            _log(f"Got an error destroying the test database: {e}")
