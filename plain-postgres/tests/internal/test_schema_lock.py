"""Tests for the schema advisory lock that serializes schema-changing commands.

The lock lives on its own database session (separate from the working
connection), so these tests observe it from the test connection via pg_locks.
"""

from __future__ import annotations

import psycopg
import pytest

from plain.postgres.db import get_connection
from plain.postgres.schema_lock import (
    SCHEMA_LOCK_KEY,
    SchemaLockTimeout,
    schema_lock,
)
from plain.postgres.sources import build_connection_params


def _lock_holder_count() -> int:
    with get_connection().cursor() as cursor:
        cursor.execute(
            """
            SELECT count(*)
            FROM pg_locks
            WHERE locktype = 'advisory'
              AND classid = %s
              AND objid = %s
              AND objsubid = 1
              AND granted
              AND database = (
                SELECT oid FROM pg_database WHERE datname = current_database()
              )
            """,
            [SCHEMA_LOCK_KEY >> 32, SCHEMA_LOCK_KEY & 0xFFFFFFFF],
        )
        row = cursor.fetchone()
        assert row is not None
        return row[0]


def test_lock_held_during_block_and_released_after(db):
    assert _lock_holder_count() == 0

    with schema_lock():
        assert _lock_holder_count() == 1

    assert _lock_holder_count() == 0


def test_lock_reacquirable_after_release(db):
    with schema_lock():
        pass

    with schema_lock():
        assert _lock_holder_count() == 1


def test_acquisition_times_out_when_held_by_another_session(db, settings):
    settings.POSTGRES_SCHEMA_LOCK_RETRY_INTERVAL = 0.01
    settings.POSTGRES_SCHEMA_LOCK_MAX_RETRIES = 3

    # Hold the lock from a separate session, like another process would.
    params = build_connection_params(get_connection().settings_dict)
    with psycopg.connect(**params, autocommit=True) as holder:
        holder.execute("SELECT pg_advisory_lock(%s)", [SCHEMA_LOCK_KEY])

        with pytest.raises(SchemaLockTimeout) as exc_info:
            with schema_lock():
                pass

        # The failed acquisition didn't disturb the holder.
        assert _lock_holder_count() == 1

    message = str(exc_info.value)
    assert "3 attempt(s)" in message
    assert "pid=" in message  # identifies the holder


def test_lock_released_when_block_raises(db):
    with pytest.raises(RuntimeError):
        with schema_lock():
            raise RuntimeError("boom")

    assert _lock_holder_count() == 0


def test_nested_acquisition_raises_immediately(db):
    with schema_lock():
        with pytest.raises(RuntimeError, match="not reentrant"):
            with schema_lock():
                pass

    # The failed nested entry didn't corrupt the held flag.
    with schema_lock():
        assert _lock_holder_count() == 1


def test_invalid_retry_interval_rejected(db, settings):
    from plain.exceptions import ImproperlyConfigured

    settings.POSTGRES_SCHEMA_LOCK_RETRY_INTERVAL = 0.0

    with pytest.raises(ImproperlyConfigured, match="must be greater than 0"):
        with schema_lock():
            pass


def test_verify_passes_while_session_alive(db):
    with schema_lock() as verify:
        verify()  # no exception — session is alive, lock held


def test_verify_raises_when_lock_session_killed(db):
    from plain.postgres.schema_lock import SchemaLockLost

    with schema_lock() as verify:
        # Find the lock holder's backend pid and kill it, simulating an
        # idle-session timeout / NAT drop / failover.
        with get_connection().cursor() as cursor:
            cursor.execute(
                """
                SELECT pid FROM pg_locks
                WHERE locktype = 'advisory'
                  AND classid = %s AND objid = %s AND objsubid = 1 AND granted
                  AND database = (
                    SELECT oid FROM pg_database WHERE datname = current_database()
                  )
                """,
                [SCHEMA_LOCK_KEY >> 32, SCHEMA_LOCK_KEY & 0xFFFFFFFF],
            )
            row = cursor.fetchone()
            assert row is not None
            cursor.execute("SELECT pg_terminate_backend(%s)", [row[0]])

        with pytest.raises(SchemaLockLost, match="re-run the command"):
            verify()
