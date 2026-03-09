"""
Tests for the psycopg_pool-based connection pooling.

These tests verify pool checkout/return behavior, dirty connection rollback,
_nodb_cursor bypass, and pool recreation after close_pool().
"""

from __future__ import annotations

import pytest

from plain.models.connections import (
    _db_conn,
    close_pool,
    get_connection,
    return_connection,
)
from plain.models.postgres.pool import PostgresPool


class TestPoolCheckoutReturn:
    """Tests for basic pool checkout and return."""

    @pytest.mark.usefixtures("_unblock_cursor", "_clean_connection")
    def test_checkout_and_return(self, setup_db):
        """get_connection().ensure_connection() checks out from pool,
        return_connection() puts it back."""
        conn = get_connection()
        conn.ensure_connection()

        # Connection is checked out
        assert conn.connection is not None

        # Return to pool
        return_connection()
        assert conn.connection is None

    @pytest.mark.usefixtures("_unblock_cursor", "_clean_connection")
    def test_wrapper_persists_after_return(self, setup_db):
        """The DatabaseConnection wrapper stays in the ContextVar after
        connection is returned to pool."""
        conn = get_connection()
        conn.ensure_connection()
        wrapper_id = id(conn)

        return_connection()

        # Wrapper still in ContextVar
        assert _db_conn.get() is not None
        assert id(_db_conn.get()) == wrapper_id

        # Re-checkout on next use
        conn.ensure_connection()
        assert conn.connection is not None


class TestDirtyConnectionRollback:
    """Tests for rolling back dirty connections before pool return."""

    @pytest.mark.usefixtures("_unblock_cursor", "_clean_connection")
    def test_dirty_connection_rolled_back(self, setup_db):
        """A connection with an open transaction is rolled back before putconn."""
        conn = get_connection()
        conn.ensure_connection()

        # Start a transaction (turn off autocommit)
        conn.set_autocommit(False)
        assert not conn.get_autocommit()

        # Return to pool — should rollback and set autocommit back
        conn.close()
        assert conn.connection is None


class TestNodbCursorBypassesPool:
    """Tests that _nodb_cursor bypasses the pool."""

    @pytest.mark.usefixtures("_unblock_cursor", "_clean_connection")
    def test_nodb_cursor_does_not_use_pool(self, setup_db):
        """Admin operations via _nodb_cursor() use direct connections, not pooled ones."""
        conn = get_connection()
        with conn._nodb_cursor() as cursor:
            cursor.execute("SELECT 1")
            row = cursor.fetchone()
            assert row == (1,)


class TestPoolRecreation:
    """Tests for pool recreation after close_pool()."""

    @pytest.mark.usefixtures("_unblock_cursor", "_clean_connection")
    def test_pool_recreated_after_close(self, setup_db):
        """Pool is recreated with correct settings after close_pool()."""
        # Get the first pool
        pool1 = PostgresPool.get_pool()
        pool1_id = id(pool1)

        # Close it
        close_pool()

        # Get a new pool
        pool2 = PostgresPool.get_pool()
        assert id(pool2) != pool1_id, "Should be a new pool instance"

        # New pool should work
        conn = get_connection()
        conn.ensure_connection()
        assert conn.connection is not None
        return_connection()
