"""
Database test helpers.
"""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager

from ..db import get_connection

__all__ = ["capture_queries", "max_queries"]


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
