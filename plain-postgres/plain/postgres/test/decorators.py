"""
Declarative test decorators for database behavior.
"""

from __future__ import annotations

from collections.abc import Callable

from plain.test import tag

__all__ = ["isolated_db"]

ISOLATED_DB_TAG = "postgres:isolated_db"


def isolated_db(func: Callable) -> Callable:
    """
    Run this test against its own separately-created database instead of a
    rolled-back transaction on the shared test database.

    For tests that exercise DDL or transaction behavior itself (migrations,
    convergence, commit semantics) — anything that can't run inside a
    transaction that never commits.

        @isolated_db
        def test_convergence_adds_index():
            ...
    """
    return tag(ISOLATED_DB_TAG)(func)
