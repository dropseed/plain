"""
Database test helpers.
"""

from collections.abc import Generator
from contextlib import contextmanager

from opentelemetry.semconv.attributes.db_attributes import DB_QUERY_TEXT
from plain.test import CapturedSpans

from ..db import get_connection

__all__ = ["capture_queries", "max_queries", "span_sql_statements"]


@contextmanager
def capture_queries() -> Generator[list[dict]]:
    """
    Record the SQL executed within the block.

        with capture_queries() as queries:
            list(qs)
        assert len(queries) == 1

    The yielded list is populated when the block exits with the executed
    query dicts (each has a "sql" key), so inspect it after the `with`.
    """
    conn = get_connection()
    previous = conn.force_debug_cursor
    conn.force_debug_cursor = True
    conn.queries_log.clear()
    captured: list[dict] = []
    try:
        yield captured
    finally:
        captured.extend(conn.queries_log)
        conn.force_debug_cursor = previous


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
        sql_lines = "\n".join(f"  {q['sql']}" for q in queries)
        raise AssertionError(
            f"Expected at most {count} queries, {executed} were executed:\n{sql_lines}"
        )


def span_sql_statements(spans: CapturedSpans, *, table: str | None = None) -> list[str]:
    """
    The SQL statements the captured database spans carry, in the order they ran.

        with capture_spans() as spans:
            store.save()
        assert span_sql_statements(spans)[0].startswith("INSERT")

    Each statement is the span's `db.query.text` -- the SQL as sent, with its
    `%s` placeholders rather than interpolated values -- with runs of
    whitespace collapsed to single spaces. Spans that carry no SQL (a request
    span, say) are skipped.

    Pass `table` to keep only the statements that mention that table, as the
    quoted identifier: `table="users_user"` keeps statements containing
    `"users_user"`.
    """
    statements = []
    for span in spans.get_finished_spans():
        if not span.attributes or DB_QUERY_TEXT not in span.attributes:
            continue
        statement = " ".join(str(span.attributes[DB_QUERY_TEXT]).split())
        if table is not None and f'"{table}"' not in statement:
            continue
        statements.append(statement)
    return statements
