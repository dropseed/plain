"""Shared helpers for tests that manipulate raw connection state."""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager

from plain.postgres.db import _db_conn


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
