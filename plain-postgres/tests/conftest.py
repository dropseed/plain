from __future__ import annotations

from contextlib import contextmanager

import pytest

from plain.postgres.connection import DatabaseConnection
from plain.postgres.db import _db_conn, get_connection


@pytest.fixture
def capture_queries():
    """Return a context manager that records the SQL run within its block.

        with capture_queries() as queries:
            list(qs)
        assert len(queries) == 1

    ``queries`` is populated when the block exits with the executed query
    dicts (each has a ``"sql"`` key), so inspect it after the ``with``.
    """

    @contextmanager
    def _capture():
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

    return _capture


@pytest.fixture
def _unblock_cursor() -> None:
    """Restore the real cursor method (blocked by the autouse _db_disabled fixture)."""
    DatabaseConnection.cursor = getattr(DatabaseConnection, "_enabled_cursor")


@pytest.fixture
def _clean_connection():
    """Ensure the ContextVar starts empty and clean up any connection afterward."""
    token = _db_conn.set(None)
    yield
    conn = _db_conn.get()
    if conn is not None:
        try:
            conn.close()
        except Exception:
            pass
    _db_conn.reset(token)
