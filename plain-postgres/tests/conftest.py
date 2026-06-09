from __future__ import annotations

import pytest

from plain.postgres.connection import DatabaseConnection
from plain.postgres.db import _db_conn


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
