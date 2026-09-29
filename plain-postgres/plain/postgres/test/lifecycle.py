"""
Database test lifecycle, registered under the `plain.test` entry point.

Every test runs against a dedicated test database (created once per run,
migrated and converged) inside a transaction that rolls back afterward.
Tests tagged with `@isolated_db` get their own separately-created database
for the duration of the test instead of a rolled-back transaction — for
DDL-heavy tests (migrations, convergence) that can't run inside a
transaction that never commits.

The databases are the run's own, and while one is in use it is the
configured database for the whole process: see `database.py`.

The rolled-back tests share one connection, opened by the first of them.
The rollback undoes everything a test did in its transaction. What belongs
to the session and not to a transaction carries over to the next test: a
session-level advisory lock, a `LISTEN`, a server-side prepared statement.
A test that needs a session of its own is `@isolated_db`.
"""

from collections.abc import Generator
from contextlib import ExitStack, contextmanager

from plain.runtime import settings
from plain.test import CollectedTest, TestLifecycle

from .. import transaction
from ..base import Model
from ..db import get_connection
from ..otel import suppress_db_tracing
from ..query import QuerySet
from .database import RunDatabases, use_test_database
from .decorators import ISOLATED_DB_TAG

# A model instance that prints in less than this is printed on one line.
_ONE_LINE = 80


def describe_model_instance(instance: Model) -> str:
    """
    A model instance with its fields: `Widget(id=1, name='bolt', size='m')`,
    or one field to a line when that is long. Its `repr` is its class and
    its id.

    A field that was deferred is read from where a loaded one is kept, so
    it is reported as not loaded and is not fetched.

    A field whose type says its value is a secret (`value_is_secret`: an
    encrypted field, a password) is printed as withheld. One with nothing
    in it says so, since that gives nothing away.
    """
    fields = []
    for field in instance._model_meta.fields:
        if field.name not in instance.__dict__:
            fields.append(f"{field.name}=<not loaded>")
            continue
        value = instance.__dict__[field.name]
        if field.value_is_secret and value not in (None, ""):
            fields.append(f"{field.name}=<withheld>")
        else:
            fields.append(f"{field.name}={value!r}")

    name = type(instance).__name__
    on_one_line = f"{name}({', '.join(fields)})"
    if len(on_one_line) <= _ONE_LINE:
        return on_one_line
    return "\n".join([f"{name}(", *(f"    {field}," for field in fields), ")"])


def describe_queryset(queryset: QuerySet) -> str:
    """
    A queryset by what it holds. One that has run prints its rows. One that
    hasn't prints the SQL it would run, and doesn't run it.
    """
    name = f"{type(queryset).__name__} of {queryset.model.__name__}"
    rows = queryset._result_cache
    if rows is not None:
        count = "1 row" if len(rows) == 1 else f"{len(rows):,} rows"
        return f"<{name}, {count}: {rows!r}>"
    try:
        # Compiled from a copy. Compiling settles a query's joins and
        # aliases, which is a change to the test's own queryset.
        sql, params = queryset._chain().sql_query.sql_with_params()
    except Exception:
        return f"<{name}, not run>"
    return f"<{name}, not run: {sql} with {params!r}>"


class PostgresTestLifecycle(TestLifecycle):
    required_package = "plain.postgres"

    def __init__(self) -> None:
        # Holds the run's claim and its shared database, from setup to teardown.
        self._test_database = ExitStack()
        self._run: RunDatabases | None = None

    def setup_worker(self) -> None:
        run = RunDatabases(
            runtime_url=str(settings.POSTGRES_URL),
            management_url=str(settings.POSTGRES_MANAGEMENT_URL),
        )
        self._run = run
        with suppress_db_tracing():
            run.claim()
            self._test_database.callback(run.release)
            self._test_database.enter_context(
                use_test_database(
                    name=run.shared_name,
                    runtime_url=run.runtime_url,
                    management_url=run.management_url,
                    verbosity=0,
                )
            )

    def teardown_worker(self) -> None:
        with suppress_db_tracing():
            # Closes the connection the tests shared, drops the database,
            # then gives up the run's claim.
            self._test_database.close()

    @contextmanager
    def around_test(self, test: CollectedTest) -> Generator[None]:
        if ISOLATED_DB_TAG in test.tags:
            yield from self._run_in_isolated_database(test)
        else:
            yield from self._run_in_rolled_back_transaction()

    def describe_value(self, value: object) -> str | None:
        if isinstance(value, Model):
            return describe_model_instance(value)
        if isinstance(value, QuerySet):
            return describe_queryset(value)
        return None

    def _run_in_rolled_back_transaction(self) -> Generator[None]:
        with suppress_db_tracing():
            atomic = transaction.atomic()
            atomic._from_testcase = True
            atomic.__enter__()
            # The transaction isn't open yet: the driver begins it with the
            # first statement. Until then, code that opens psycopg's own
            # `connection.transaction()` finds none, begins one itself, and
            # commits it, and what it did outlives the test. So send the
            # first statement here. The connection was the last test's too,
            # and a session-level advisory lock is the session's, which a
            # rollback doesn't release: the statement gives back any that
            # test left held.
            with get_connection().cursor() as cursor:
                cursor.execute("SELECT pg_advisory_unlock_all()")

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
        run = self._run
        assert run is not None
        test_name = test.id.rpartition("::")[2]

        ctx = use_test_database(
            name=run.isolated_name(test_name),
            runtime_url=run.runtime_url,
            management_url=run.management_url,
            verbosity=0,
        )
        with suppress_db_tracing():
            ctx.__enter__()
        try:
            yield
        finally:
            with suppress_db_tracing():
                ctx.__exit__(None, None, None)
