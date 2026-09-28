"""
Database test lifecycle, registered under the `plain.test` entry point.

Every test runs against a dedicated test database (created once per run,
migrated and converged) inside a transaction that rolls back afterward.
Tests tagged with `@isolated_db` get their own separately-created database
for the duration of the test instead of a rolled-back transaction — for
DDL-heavy tests (migrations, convergence) that can't run inside a
transaction that never commits.

The rolled-back tests share one connection, opened by the first of them.
The rollback undoes everything a test did in its transaction. What belongs
to the session and not to a transaction carries over to the next test: a
session-level advisory lock, a `LISTEN`, a server-side prepared statement.
A test that needs a session of its own is `@isolated_db`.
"""

import re
from collections.abc import Generator
from contextlib import ExitStack, contextmanager

from plain.test import CollectedTest, TestLifecycle

from .. import transaction
from ..db import get_connection
from ..otel import suppress_db_tracing
from ..sources import runtime_pool_source
from .database import use_test_database
from .decorators import ISOLATED_DB_TAG


class PostgresTestLifecycle(TestLifecycle):
    required_package = "plain.postgres"

    def __init__(self) -> None:
        # Holds the test database open from setup to teardown.
        self._test_database = ExitStack()

    def setup_worker(self) -> None:
        # use_test_database installs a direct connection to the test database
        # via the connection ContextVar; close any existing pool so nothing
        # keeps handing out connections opened against the runtime URL.
        runtime_pool_source.close()
        with suppress_db_tracing():
            self._test_database.enter_context(use_test_database(verbosity=0, prefix=""))

    def teardown_worker(self) -> None:
        with suppress_db_tracing():
            # Closes the connection the tests shared, then drops the database.
            self._test_database.close()
        runtime_pool_source.close()

    @contextmanager
    def around_test(self, test: CollectedTest) -> Generator[None]:
        if ISOLATED_DB_TAG in test.tags:
            yield from self._run_in_isolated_database(test)
        else:
            yield from self._run_in_rolled_back_transaction()

    def _run_in_rolled_back_transaction(self) -> Generator[None]:
        with suppress_db_tracing():
            atomic = transaction.atomic()
            atomic._from_testcase = True
            atomic.__enter__()
            # The transaction isn't open yet: the driver begins it with the
            # first statement. Until then, code that opens psycopg's own
            # `connection.transaction()` finds none, begins one itself, and
            # commits it, and what it did outlives the test. So send the
            # first statement here.
            with get_connection().cursor() as cursor:
                cursor.execute("SELECT 1")

        try:
            yield
        finally:
            with suppress_db_tracing():
                # Constraints are never deferred (foreign keys are NOT
                # DEFERRABLE), so there is nothing to check before rolling
                # back — the database has already rejected any violation.
                get_connection().set_rollback(True)
                atomic.__exit__(None, None, None)
                # The connection stays open for the next test. Opening one
                # costs a hundred times what the rollback does.

    def _run_in_isolated_database(self, test: CollectedTest) -> Generator[None]:
        test_name = test.id.rpartition("::")[2]
        prefix = re.sub(r"[^0-9A-Za-z_]+", "_", test_name)

        # Per-test pool, rebuilt against this test's database.
        runtime_pool_source.close()
        ctx = use_test_database(verbosity=0, prefix=prefix)
        with suppress_db_tracing():
            ctx.__enter__()
        try:
            yield
        finally:
            with suppress_db_tracing():
                ctx.__exit__(None, None, None)
            runtime_pool_source.close()
