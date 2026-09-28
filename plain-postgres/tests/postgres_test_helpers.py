"""Shared helpers for the plain-postgres tests."""

from collections.abc import Generator
from contextlib import contextmanager

from plain.postgres.db import _db_conn
from plain.postgres.test import CapturedQueries


@contextmanager
def clean_connection() -> Generator[None]:
    """Start the connection ContextVar empty and clean up any connection
    created inside the block, restoring the previous connection on exit."""
    token = _db_conn.set(None)
    try:
        yield
    finally:
        conn = _db_conn.get()
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
        _db_conn.reset(token)


def executed_sql(queries: CapturedQueries) -> str:
    """Join the statements recorded by ``capture_queries`` into one string.

        with capture_queries() as queries:
            Model.query.filter(...).delete()
        assert "FOR UPDATE" in executed_sql(queries)

    Transaction control is left out -- savepoints included, which the test
    lifecycle wraps every test in -- so a block inside ``atomic()`` reads the
    same as one that wasn't, and what comes back is replayable SQL.
    """
    control = ("BEGIN", "COMMIT", "ROLLBACK", "SAVEPOINT", "RELEASE")
    return " ".join(
        query.sql_with_params
        for query in queries
        if not query.sql_with_params.startswith(control)
    )
