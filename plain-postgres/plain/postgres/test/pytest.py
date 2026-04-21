from __future__ import annotations

import re
from collections.abc import Generator
from typing import Any

import pytest

from plain.postgres.otel import suppress_db_tracing
from plain.signals import request_finished, request_started

from .. import transaction
from ..connection import DatabaseConnection
from ..db import close_old_connections, get_connection
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

    # Keep connections open during request client / testing. Disconnect
    # before entering `use_test_database` — migrations and convergence run
    # inside it and we don't want close_old_connections firing in that window.
    request_started.disconnect(close_old_connections)
    request_finished.disconnect(close_old_connections)
    try:
        ctx = use_test_database(verbosity=verbosity)
        with suppress_db_tracing():
            ctx.__enter__()
        try:
            yield
        finally:
            with suppress_db_tracing():
                ctx.__exit__(None, None, None)
    finally:
        request_started.connect(close_old_connections)
        request_finished.connect(close_old_connections)


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
        # PostgreSQL can defer constraint checks
        if not conn.needs_rollback and conn.is_usable():
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

    ctx = use_test_database(verbosity=verbosity, prefix=prefix)
    with suppress_db_tracing():
        ctx.__enter__()
    try:
        yield
    finally:
        with suppress_db_tracing():
            ctx.__exit__(None, None, None)
