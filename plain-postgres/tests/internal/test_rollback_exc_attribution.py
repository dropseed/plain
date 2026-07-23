"""Regression test for stale `rollback_exc` attribution across transactions.

`connection.rollback_exc` records the exception behind a pending rollback so
`validate_no_broken_transaction()` can chain a `TransactionManagementError`
`from` it. The wrapper holding it is reused across `atomic()` blocks, so it
must not survive the transaction that set it — otherwise a later broken
transaction chains `from` a previous, unrelated transaction's exception.

It's now cleared on entry to an outermost `atomic()` block, and the real cause
is recorded when a savepoint-less nested block marks the transaction for
rollback.
"""

from __future__ import annotations

import psycopg
import pytest

from plain.postgres import transaction
from plain.postgres.db import get_connection


def _execute(sql: str) -> None:
    with get_connection().cursor() as cursor:
        cursor.execute(sql)


def _fail_in_savepoint_via_mark(sql: str) -> None:
    """Mimic Model.create()/update(): a query that fails inside a savepoint,
    routed through mark_for_rollback_on_error() so rollback_exc is set."""
    with transaction.atomic():  # savepoint
        with transaction.mark_for_rollback_on_error():
            _execute(sql)


def _fail_in_savepointless_block(sql: str) -> None:
    """A failure inside a savepoint-less nested block, which marks the whole
    transaction for rollback without a savepoint to roll back to."""
    with transaction.atomic(savepoint=False):
        _execute(sql)


class TestRollbackExcAttribution:
    def test_broken_transaction_not_attributed_to_prior_transaction(self, isolated_db):
        conn = get_connection()

        # Transaction 1: a caught failure through the Model.create()/update()
        # path sets rollback_exc, which is not cleared when the block ends.
        with transaction.atomic():
            with pytest.raises(psycopg.errors.UndefinedTable):
                _fail_in_savepoint_via_mark("SELECT * FROM txn1_missing_table")

        # rollback_exc lingers on the reused wrapper until the next outermost
        # atomic() block clears it (documents the leak this test guards).
        assert conn.rollback_exc is not None
        assert "txn1_missing_table" in str(conn.rollback_exc)

        # Transaction 2: unrelated work that breaks the transaction via a
        # savepoint-less nested block, then runs another query.
        with transaction.atomic():
            with pytest.raises(psycopg.errors.UndefinedTable):
                _fail_in_savepointless_block("SELECT * FROM txn2_missing_table")

            with pytest.raises(transaction.TransactionManagementError) as excinfo:
                _execute("SELECT 1")

        cause = excinfo.value.__cause__
        # The regression: the cause must not be transaction 1's exception.
        assert "txn1_missing_table" not in str(cause)
        # And it should be transaction 2's actual failure.
        assert cause is not None
        assert "txn2_missing_table" in str(cause)

    def test_clean_outermost_atomic_starts_without_a_cause(self, isolated_db):
        conn = get_connection()

        # Leave a stale rollback_exc behind, as transaction 1 above does.
        with transaction.atomic():
            with pytest.raises(psycopg.errors.UndefinedTable):
                _fail_in_savepoint_via_mark("SELECT * FROM stale_table")
        assert conn.rollback_exc is not None

        # Entering a fresh outermost block clears it.
        with transaction.atomic():
            assert conn.rollback_exc is None
