"""A failed increment must mark the connection for rollback.

`increment()` runs raw SQL; a non-numeric value raises `DataError`, which leaves
the Postgres transaction aborted. If the caller catches that error inside an
`atomic()` block, the block must still roll back rather than silently commit
earlier writes and run commit hooks. This pins the mechanism -- the connection's
`needs_rollback` flag -- the same guard the ORM write paths use.
"""

from __future__ import annotations

import psycopg

from plain.cache import cache
from plain.postgres import get_connection
from plain.test import raises


def test_failed_increment_marks_transaction_for_rollback():
    # Every test runs inside transaction.atomic(), so the connection is in
    # an atomic block here -- the production scenario.
    cache.set("text", "not a number")

    with raises(psycopg.DataError):
        cache.increment("text")

    # The error is caught here, but the connection is flagged so the enclosing
    # atomic() rolls back instead of committing earlier writes.
    assert get_connection().needs_rollback is True
