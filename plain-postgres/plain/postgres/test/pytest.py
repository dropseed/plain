from __future__ import annotations

import re
from collections.abc import Generator
from typing import Any

import pytest
from psycopg import pq

from plain.postgres.otel import suppress_db_tracing

from .. import transaction
from ..connection import DatabaseConnection
from ..db import get_connection
from ..sources import runtime_pool_source
from .database import use_test_database


@pytest.fixture(autouse=True)
def _db_disabled() -> Generator[None]:
    """
    Every test should use this fixture by default to prevent
    access to the normal database.
    """

    def cursor_disabled(self: Any) -> None:
        pytest.fail("Database access not allowed without the `db` fixture")  # ty: ignore[invalid-argument-type]

    # Save original cursor method and replace with disabled version
    setattr(DatabaseConnection, "_enabled_cursor", DatabaseConnection.cursor)
    DatabaseConnection.cursor = cursor_disabled  # ty: ignore[invalid-assignment]

    yield

    # Restore original cursor method
    DatabaseConnection.cursor = getattr(DatabaseConnection, "_enabled_cursor")


@pytest.fixture(scope="session")
def setup_db(request: Any) -> Generator[None]:
    """
    This fixture is called automatically by `db`,
    so a test database will only be setup if the `db` fixture is used.
    """
    verbosity = request.config.option.verbose

    # Test DB points at a different database name, so a pool built
    # against the runtime URL would connect to the wrong place. Close
    # any existing pool so the next checkout rebuilds against the
    # active POSTGRES_URL (which use_test_database swaps).
    runtime_pool_source.close()
    ctx = use_test_database(verbosity=verbosity)
    with suppress_db_tracing():
        ctx.__enter__()
    try:
        yield
    finally:
        with suppress_db_tracing():
            ctx.__exit__(None, None, None)
        runtime_pool_source.close()


@pytest.fixture
def db(setup_db: Any, request: Any) -> Generator[None]:
    if "isolated_db" in request.fixturenames:
        pytest.fail("The 'db' and 'isolated_db' fixtures cannot be used together")  # ty: ignore[invalid-argument-type]

    # Set .cursor() back to the original implementation to unblock it
    DatabaseConnection.cursor = getattr(DatabaseConnection, "_enabled_cursor")

    with suppress_db_tracing():
        atomic = transaction.atomic()
        atomic._from_testcase = True
        atomic.__enter__()

    yield

    with suppress_db_tracing():
        conn = get_connection()
        # PostgreSQL can defer constraint checks. Skip when the connection is
        # already in an aborted-transaction state (e.g. the test raised a
        # DB error) — further commands would just raise InFailedSqlTransaction.
        if (
            not conn.needs_rollback
            and conn.connection is not None
            and conn.connection.info.transaction_status != pq.TransactionStatus.INERROR
        ):
            conn.check_constraints()

        conn.set_rollback(True)
        atomic.__exit__(None, None, None)

        conn.close()


@pytest.fixture
def isolated_db(request: Any) -> Generator[None]:
    """
    Create and destroy a unique test database for each test, using a prefix
    derived from the test function name to ensure isolation from the default
    test database.
    """
    if "db" in request.fixturenames:
        pytest.fail("The 'db' and 'isolated_db' fixtures cannot be used together")  # ty: ignore[invalid-argument-type]
    # Set .cursor() back to the original implementation to unblock it
    DatabaseConnection.cursor = getattr(DatabaseConnection, "_enabled_cursor")

    verbosity = 1

    # Derive a safe prefix from the test function name
    raw_name = request.node.name
    prefix = re.sub(r"[^0-9A-Za-z_]+", "_", raw_name)

    # Per-test pool, rebuilt against this test's DB.
    runtime_pool_source.close()
    ctx = use_test_database(verbosity=verbosity, prefix=prefix)
    with suppress_db_tracing():
        ctx.__enter__()
    try:
        yield
    finally:
        with suppress_db_tracing():
            ctx.__exit__(None, None, None)
        runtime_pool_source.close()
