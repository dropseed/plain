from __future__ import annotations

import pytest

from plain.models.connections import _db_conn
from plain.models.postgres.connection import DatabaseConnection


@pytest.fixture
def _unblock_cursor():
    """Restore the real cursor method (blocked by the autouse _db_disabled fixture)."""
    DatabaseConnection.cursor = getattr(DatabaseConnection, "_enabled_cursor")


@pytest.fixture
def _clean_connection():
    """Ensure the ContextVar starts empty and clean up any connection afterward."""
    # Return any existing connection to the pool before clearing
    existing = _db_conn.get()
    if existing is not None and existing.connection is not None:
        try:
            existing.close()
        except Exception:
            pass
    token = _db_conn.set(None)
    yield
    conn = _db_conn.get()
    if conn is not None:
        try:
            conn.close()
        except Exception:
            pass
    _db_conn.reset(token)
