from __future__ import annotations

import pytest

from plain.postgres.connection import DatabaseConnection


@pytest.fixture
def _unblock_cursor() -> None:
    """Restore the real cursor method (blocked by the autouse _db_disabled fixture)."""
    DatabaseConnection.cursor = getattr(DatabaseConnection, "_enabled_cursor")
