"""
Database test lifecycle, registered under the `plain.testing` entry point.

Every test runs against a dedicated test database (created once per worker,
migrated and converged) inside a transaction that rolls back afterward.
Tests tagged with `@isolated_db` get their own separately-created database
for the duration of the test instead of a rolled-back transaction — for
DDL-heavy tests (migrations, convergence) that can't run inside a
transaction that never commits.
"""

from __future__ import annotations

import re
from collections.abc import Generator
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any

from psycopg import pq

from plain.test import TestLifecycle

from .. import transaction
from ..db import get_connection
from ..otel import suppress_db_tracing
from ..sources import runtime_pool_source
from .database import use_test_database
from .decorators import ISOLATED_DB_TAG

if TYPE_CHECKING:
    from plain.testing.collection import CollectedTest


class PostgresTestLifecycle(TestLifecycle):
    required_package = "plain.postgres"

    def __init__(self) -> None:
        self._worker_db_ctx: Any = None

    def setup_worker(self) -> None:
        # use_test_database installs a direct connection to the test database
        # via the connection ContextVar; close any existing pool so nothing
        # keeps handing out connections opened against the runtime URL.
        runtime_pool_source.close()
        self._worker_db_ctx = use_test_database(verbosity=0, prefix="")
        with suppress_db_tracing():
            self._worker_db_ctx.__enter__()

    def teardown_worker(self) -> None:
        if self._worker_db_ctx is not None:
            with suppress_db_tracing():
                self._worker_db_ctx.__exit__(None, None, None)
            self._worker_db_ctx = None
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

        try:
            yield
        finally:
            with suppress_db_tracing():
                conn = get_connection()
                # PostgreSQL can defer constraint checks. Skip when the
                # connection is already in an aborted-transaction state (e.g.
                # the test raised a DB error) — further commands would just
                # raise InFailedSqlTransaction.
                if (
                    not conn.needs_rollback
                    and conn.connection is not None
                    and conn.connection.info.transaction_status
                    != pq.TransactionStatus.INERROR
                ):
                    conn.check_constraints()

                conn.set_rollback(True)
                atomic.__exit__(None, None, None)

                conn.close()

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
