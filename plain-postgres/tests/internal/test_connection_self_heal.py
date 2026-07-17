"""Tests for self-healing after a server-side connection close.

When Postgres closes a connection we're holding (restart, failover, idle
timeout), psycopg only notices on the next I/O — the operation fails and the
connection is marked closed. `ensure_connection()` must then discard the dead
connection and acquire a fresh one, instead of reusing the dead object on
every subsequent call.

The exception is inside an atomic block: swapping there would silently run
the rest of the block outside its transaction, so the dead connection stays
put and `Atomic.__exit__`'s error recovery drops it instead.
"""

from __future__ import annotations

import psycopg
from helpers import clean_connection

from plain.postgres import transaction
from plain.postgres.db import get_connection
from plain.postgres.sources import runtime_pool_source
from plain.test import raises


def _terminate_backend(pid: int) -> None:
    """Kill a backend from a separate pool connection."""
    terminator = runtime_pool_source.acquire()
    try:
        with terminator.cursor() as cursor:
            cursor.execute("SELECT pg_terminate_backend(%s)", (pid,))
    finally:
        runtime_pool_source.release(terminator)


def _backend_pid(conn) -> int:
    with conn.cursor() as cursor:
        cursor.execute("SELECT pg_backend_pid()")
        row = cursor.fetchone()
        assert row is not None
        return row[0]


class TestDeadConnectionSelfHeal:
    def test_closed_connection_replaced_on_next_use(self):
        """A wrapper holding a closed psycopg connection acquires a fresh one."""
        with clean_connection():
            conn = get_connection()
            with conn.cursor() as cursor:
                cursor.execute("SELECT 1")

            # Simulate the aftermath of a server-side close: the wrapper still
            # holds a psycopg connection whose pgconn status is BAD.
            assert conn.connection is not None
            conn.connection.close()
            assert conn.connection.closed

            with conn.cursor() as cursor:
                cursor.execute("SELECT 1")
                assert cursor.fetchone() == (1,)
            assert conn.connection is not None
            assert not conn.connection.closed

    def test_terminated_backend_errors_once_then_heals(self):
        """A server-side kill fails the in-flight query, then self-heals."""
        with clean_connection():
            conn = get_connection()
            pid = _backend_pid(conn)

            _terminate_backend(pid)

            # psycopg only detects the dead socket on I/O — the first use fails
            # and marks the connection closed.
            with raises(psycopg.OperationalError):
                with conn.cursor() as cursor:
                    cursor.execute("SELECT 1")
            assert conn.connection is not None
            assert conn.connection.closed

            # The next use discards the dead connection and acquires a fresh one.
            with conn.cursor() as cursor:
                cursor.execute("SELECT 1")
                assert cursor.fetchone() == (1,)
            assert _backend_pid(conn) != pid

    def test_dead_connection_not_swapped_mid_atomic(self):
        """Mid-atomic, the dead connection stays put — a silent swap would run
        the rest of the block outside its transaction. Atomic.__exit__'s error
        recovery drops it, and the next use heals."""
        with clean_connection():
            conn = get_connection()

            def killed_mid_atomic() -> None:
                with transaction.atomic():
                    pid = _backend_pid(conn)
                    _terminate_backend(pid)
                    with conn.cursor() as cursor:
                        cursor.execute("SELECT 1")

            with raises(psycopg.OperationalError):
                killed_mid_atomic()

            # Atomic.__exit__ dropped the dead connection during rollback recovery.
            assert conn.connection is None

            with conn.cursor() as cursor:
                cursor.execute("SELECT 1")
                assert cursor.fetchone() == (1,)

    def test_dead_connection_in_nested_atomic(self):
        """Nested atomics: the inner savepoint rollback fails on the dead
        connection and marks needs_rollback; the outer rollback then fails
        too and drops the connection. The next use heals."""
        with clean_connection():
            conn = get_connection()

            def killed_in_nested_atomic() -> None:
                with transaction.atomic():
                    with transaction.atomic():
                        pid = _backend_pid(conn)
                        _terminate_backend(pid)
                        with conn.cursor() as cursor:
                            cursor.execute("SELECT 1")

            with raises(psycopg.OperationalError):
                killed_in_nested_atomic()

            # The outer Atomic.__exit__ dropped the dead connection.
            assert conn.connection is None

            with conn.cursor() as cursor:
                cursor.execute("SELECT 1")
                assert cursor.fetchone() == (1,)
