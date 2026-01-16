from __future__ import annotations

import re
from collections.abc import Generator
from typing import Any

import pytest

from plain.models.otel import suppress_db_tracing
from plain.signals import request_finished, request_started

from .. import transaction
from ..backends.wrapper import DatabaseWrapper
from ..db import close_old_connections, db_connection
from .utils import (
    setup_database,
    teardown_database,
)


@pytest.fixture(autouse=True)
def _db_disabled() -> Generator[None, None, None]:
    """
    Every test should use this fixture by default to prevent
    access to the normal database.
    """

    def cursor_disabled(self: Any) -> None:
        pytest.fail("Database access not allowed without the `db` fixture")

    # Save original cursor method and replace with disabled version
    setattr(DatabaseWrapper, "_enabled_cursor", DatabaseWrapper.cursor)
    DatabaseWrapper.cursor = cursor_disabled  # type: ignore[assignment]

    yield

    # Restore original cursor method
    DatabaseWrapper.cursor = getattr(DatabaseWrapper, "_enabled_cursor")


@pytest.fixture(scope="session")
def setup_db(request: Any) -> Generator[None, None, None]:
    """
    This fixture is called automatically by `db`,
    so a test database will only be setup if the `db` fixture is used.
    """
    verbosity = request.config.option.verbose

    # Set up the test db across the entire session
    _old_db_name = setup_database(verbosity=verbosity)

    # Keep connections open during request client / testing
    request_started.disconnect(close_old_connections)
    request_finished.disconnect(close_old_connections)

    yield

    # Put the signals back...
    request_started.connect(close_old_connections)
    request_finished.connect(close_old_connections)

    # When the test session is done, tear down the test db
    teardown_database(_old_db_name, verbosity=verbosity)


@pytest.fixture
def db(setup_db: Any, request: Any) -> Generator[None, None, None]:
    if "isolated_db" in request.fixturenames:
        pytest.fail("The 'db' and 'isolated_db' fixtures cannot be used together")

    # Set .cursor() back to the original implementation to unblock it
    DatabaseWrapper.cursor = getattr(DatabaseWrapper, "_enabled_cursor")

    with suppress_db_tracing():
        atomic = transaction.atomic()
        atomic._from_testcase = True
        atomic.__enter__()

    yield

    with suppress_db_tracing():
        # PostgreSQL can defer constraint checks
        if not db_connection.needs_rollback and db_connection.is_usable():
            db_connection.check_constraints()

        db_connection.set_rollback(True)
        atomic.__exit__(None, None, None)

        db_connection.close()


@pytest.fixture
def isolated_db(request: Any) -> Generator[None, None, None]:
    """
    Create and destroy a unique test database for each test, using a prefix
    derived from the test function name to ensure isolation from the default
    test database.
    """
    if "db" in request.fixturenames:
        pytest.fail("The 'db' and 'isolated_db' fixtures cannot be used together")
    # Set .cursor() back to the original implementation to unblock it
    DatabaseWrapper.cursor = getattr(DatabaseWrapper, "_enabled_cursor")

    verbosity = 1

    # Derive a safe prefix from the test function name
    raw_name = request.node.name
    prefix = re.sub(r"[^0-9A-Za-z_]+", "_", raw_name)

    # Set up a fresh test database for this test, using the prefix
    _old_db_name = setup_database(verbosity=verbosity, prefix=prefix)

    yield

    # Tear down the test database created for this test
    teardown_database(_old_db_name, verbosity=verbosity)
