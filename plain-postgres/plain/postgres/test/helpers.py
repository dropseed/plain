"""
Database test helpers.
"""

from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
from functools import partial
from typing import Any
from weakref import WeakKeyDictionary

from plain.testing import Captured, CaptureSource

from ..connection import DatabaseConnection
from ..db import get_connection

__all__ = ["CapturedQueries", "CapturedQuery", "capture_queries", "max_queries"]


@dataclass(frozen=True)
class CapturedQuery:
    """One thing the database was asked to do during a `capture_queries` block."""

    # The statement as it was sent: `%s` placeholders in place, values apart.
    sql: str
    # The same statement with the values filled in. An `executemany()` is one
    # query here, prefixed with how many times it ran: "3 times: INSERT ...".
    sql_with_params: str
    # False for BEGIN, COMMIT and ROLLBACK, which the connection issues
    # itself. A savepoint is a statement like any other.
    is_statement: bool


class CapturedQueries(Captured[CapturedQuery]):
    """
    What the database was asked to do during a `capture_queries` block, in
    the order it was asked.
    """

    def __init__(self) -> None:
        super().__init__(helper="capture_queries")

    def sql_statements(self, *, table: str | None = None) -> list[str]:
        """
        The statements as they were sent, with runs of whitespace collapsed
        to single spaces — the form to compare against SQL written out in a
        test.

            with capture_queries() as queries:
                cache.set_many({"a": 1, "b": 2})

            [statement] = queries.sql_statements()
            assert statement.startswith('INSERT INTO "plaincache_cacheditem"')

        Savepoints are statements and are here. BEGIN, COMMIT and ROLLBACK
        are not: the connection issues those itself.

        Pass `table` to keep only the statements that name that table as a
        quoted identifier: `table="users_user"` keeps the statements that
        contain `"users_user"`.
        """
        statements = []
        for query in self:
            if not query.is_statement:
                continue
            statement = " ".join(query.sql.split())
            if table is not None and f'"{table}"' not in statement:
                continue
            statements.append(statement)
        return statements


@contextmanager
def capture_queries() -> Generator[CapturedQueries]:
    """
    What the database is asked to do within the block.

        with capture_queries() as queries:
            list(Article.query.all())

        assert len(queries) == 1
        assert queries[0].sql.startswith("SELECT")

    It records at the connection, so it sees every query whether or not the
    query is traced, and whether or not the connection was returned to the
    pool and taken out again along the way, as it is by a request outside a
    transaction.
    """
    conn = get_connection()
    previous = conn.force_debug_cursor
    conn.force_debug_cursor = True
    captured = CapturedQueries()
    try:
        with _query_source_of(conn).capturing_into(captured):
            yield captured
    finally:
        conn.force_debug_cursor = previous


# Every capture on a connection reads that connection's query log, so each
# connection has one source, kept for as long as the connection is.
_query_sources: WeakKeyDictionary[DatabaseConnection, CaptureSource[CapturedQuery]] = (
    WeakKeyDictionary()
)


def _query_source_of(conn: DatabaseConnection) -> CaptureSource[CapturedQuery]:
    source = _query_sources.get(conn)
    if source is None:
        # The source holds the connection's log, not the connection, so it
        # doesn't keep a closed connection from being let go.
        source = CaptureSource(
            read=partial(_queries_in, conn.captured_queries_log),
            clear=conn.captured_queries_log.clear,
        )
        _query_sources[conn] = source
    return source


def _queries_in(queries_log: list[dict[str, Any]]) -> list[CapturedQuery]:
    return [
        CapturedQuery(
            sql=entry.get("sql_as_sent", entry["sql"]),
            sql_with_params=entry["sql"],
            is_statement="sql_as_sent" in entry,
        )
        for entry in queries_log
    ]


@contextmanager
def max_queries(count: int) -> Generator[None]:
    """
    Fail if more than `count` database queries execute within the block.

        with max_queries(5):
            client.get("/dashboard/")

    A query budget is a contract, checked on every run.
    """
    with capture_queries() as queries:
        yield
    executed = len(queries)
    if executed > count:
        sql_lines = "\n".join(f"  {query.sql_with_params}" for query in queries)
        raise AssertionError(
            f"Expected at most {count} queries, {executed} were executed:\n{sql_lines}"
        )
