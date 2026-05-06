"""Tests for the process-wide connection pool."""

from __future__ import annotations

import concurrent.futures
import threading
import time

import pytest
from psycopg_pool import PoolTimeout

from plain.postgres.db import (
    _db_conn,
    get_connection,
    return_database_connection,
)
from plain.postgres.sources import runtime_pool_source
from plain.runtime import settings


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


class TestPoolCheckoutReturn:
    @pytest.mark.usefixtures("_unblock_cursor", "_clean_connection")
    def test_checkout_and_return(self, setup_db):
        """First cursor use checks a connection out; return_database_connection puts it back."""
        conn = get_connection()
        assert conn.connection is None, "No checkout until cursor is used"

        with conn.cursor() as cursor:
            cursor.execute("SELECT 1")
        assert conn.connection is not None, "Cursor use triggers checkout"

        return_database_connection()
        assert conn.connection is None, "Inner connection is returned to pool"

    @pytest.mark.usefixtures("_unblock_cursor", "_clean_connection")
    def test_wrapper_persists_after_return(self, setup_db):
        """The wrapper stays in the ContextVar; next use checks out again."""
        conn = get_connection()
        with conn.cursor() as cursor:
            cursor.execute("SELECT 1")

        return_database_connection()
        assert conn is _db_conn.get(), "Wrapper persists across return"

        with conn.cursor() as cursor:
            cursor.execute("SELECT 1")
        assert conn.connection is not None


class TestDirtyConnectionRollback:
    @pytest.mark.usefixtures("_unblock_cursor", "_clean_connection")
    def test_dirty_connection_rolled_back(self, setup_db):
        """Returning a connection mid-transaction rolls it back and restores autocommit."""
        conn = get_connection()
        conn.ensure_connection()
        raw = conn.connection
        assert raw is not None

        raw.autocommit = False
        with raw.cursor() as cursor:
            cursor.execute("SELECT 1")

        return_database_connection()

        # Check out again — autocommit should be restored by the pool's reset callback.
        with conn.cursor() as cursor:
            cursor.execute("SELECT 1")
        assert conn.connection is not None
        assert conn.connection.autocommit is True


class TestPoolRecreation:
    def test_pool_recreated_after_close(self, setup_db):
        """PoolSource.close() drops the pool; next acquire opens a fresh one."""
        source = runtime_pool_source
        pool = source._get_pool()
        assert source._pool is pool

        source.close()
        assert source._pool is None

        new_pool = source._get_pool()
        assert new_pool is not pool


class TestConcurrentCheckouts:
    @pytest.mark.usefixtures("_unblock_cursor", "_clean_connection")
    def test_concurrent_workers_hold_distinct_connections(self, setup_db):
        """N worker threads querying simultaneously hold N distinct pool connections."""
        n_workers = 4
        barrier = threading.Barrier(n_workers)
        pids: list[int] = []
        pids_lock = threading.Lock()

        def worker() -> None:
            conn = get_connection()
            with conn.cursor() as cursor:
                cursor.execute("SELECT pg_backend_pid()")
                row = cursor.fetchone()
                assert row is not None
                pid = row[0]
            # Block until all workers have checked out a connection — proves
            # concurrency (not serialized reuse of a single connection).
            barrier.wait()
            with pids_lock:
                pids.append(pid)
            return_database_connection()

        with concurrent.futures.ThreadPoolExecutor(max_workers=n_workers) as ex:
            for future in concurrent.futures.as_completed(
                [ex.submit(worker) for _ in range(n_workers)]
            ):
                future.result()

        assert len(pids) == n_workers
        assert len(set(pids)) == n_workers, (
            f"Expected {n_workers} distinct backend pids, got {sorted(pids)}"
        )


class TestPoolSettingsWiring:
    def test_max_size_and_timeout_reach_the_pool(self, setup_db, monkeypatch):
        """POSTGRES_POOL_MAX_SIZE caps concurrent checkouts; POSTGRES_POOL_TIMEOUT bounds the wait.

        If either setting silently stopped propagating to `ConnectionPool`,
        a rename or typo would go unnoticed — existing tests all run under
        the defaults. This forces a rebuild at tiny values and proves the
        pool honors them.
        """
        runtime_pool_source.close()
        monkeypatch.setattr(settings, "POSTGRES_POOL_MIN_SIZE", 1)
        monkeypatch.setattr(settings, "POSTGRES_POOL_MAX_SIZE", 1)
        monkeypatch.setattr(settings, "POSTGRES_POOL_TIMEOUT", 0.2)
        try:
            holder = runtime_pool_source.acquire()
            try:
                start = time.monotonic()
                with pytest.raises(PoolTimeout):
                    runtime_pool_source.acquire()
                elapsed = time.monotonic() - start
                # Generous upper bound for CI noise; lower bound proves we
                # actually waited rather than failing immediately.
                assert 0.15 <= elapsed < 2.0, f"Expected ~0.2s wait, got {elapsed:.3f}s"
            finally:
                runtime_pool_source.release(holder)
        finally:
            # Rebuild at default settings for subsequent tests.
            runtime_pool_source.close()
