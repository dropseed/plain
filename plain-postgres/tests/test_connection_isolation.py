"""
Tests for database connection isolation across threads and async tasks.

These tests validate that get_connection/has_connection properly isolate connections:
- Different threads get different connections
- Different asyncio tasks get different connections
- Context propagation via copy_context().run() works (for asyncio.to_thread)

These tests directly manipulate the internal ContextVar to avoid needing a real
database — we're testing the storage/isolation mechanism, not DB connectivity.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import contextvars
import threading

import pytest

from plain.postgres.db import _db_conn, has_connection


class FakeConn:
    """Lightweight stand-in for DatabaseConnection to test storage isolation."""

    pass


@pytest.fixture(autouse=True)
def _reset_db_conn():
    """Reset the module-level ContextVar before/after each test."""
    token = _db_conn.set(None)
    yield
    _db_conn.reset(token)


def _store_fake() -> FakeConn:
    """Store a FakeConn in the ContextVar."""
    conn = FakeConn()
    _db_conn.set(conn)  # ty: ignore[invalid-argument-type]
    return conn


def test_each_thread_gets_its_own_connection():
    """Different threads must get different connection instances."""
    results: dict[str, int] = {}
    barrier = threading.Barrier(2)

    def access_connection(name: str) -> None:
        conn = _store_fake()
        results[name] = id(conn)
        barrier.wait()

    t1 = threading.Thread(target=access_connection, args=("a",))
    t2 = threading.Thread(target=access_connection, args=("b",))
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    assert results["a"] != results["b"], (
        "Threads should get different connection instances"
    )


def test_main_thread_connection_not_visible_to_child_thread():
    """A connection created on the main thread must not leak to a child thread."""
    _store_fake()
    assert has_connection()

    visible_in_child = []

    def check_child() -> None:
        visible_in_child.append(has_connection())

    t = threading.Thread(target=check_child)
    t.start()
    t.join()

    assert visible_in_child[0] is False, (
        "Child thread should not see main thread's connection"
    )


def test_async_tasks_get_isolated_connections():
    """
    Two concurrent asyncio tasks must get separate connections.

    Each asyncio.Task gets its own context copy, so two tasks on the same
    event loop thread should see different connections.
    """

    async def get_connection_id() -> int:
        conn = _store_fake()
        conn_id = id(conn)
        # Yield control so both tasks interleave
        await asyncio.sleep(0)
        # Verify we still see our own connection after yielding
        assert has_connection()
        assert id(_db_conn.get()) == conn_id, "Connection changed mid-task"
        return conn_id

    async def run() -> tuple[int, int]:
        task1 = asyncio.create_task(get_connection_id())
        task2 = asyncio.create_task(get_connection_id())
        return await task1, await task2

    id1, id2 = asyncio.run(run())
    assert id1 != id2, "Async tasks on the same thread should get different connections"


def test_async_task_connection_does_not_leak_to_next_task():
    """A connection created in one async task must not be visible to the next."""

    async def run() -> bool:
        async def set_connection() -> None:
            _store_fake()
            assert has_connection()

        async def check_connection() -> bool:
            return has_connection()

        # First task creates a connection
        await asyncio.create_task(set_connection())
        # Second task should start with a clean slate
        return await asyncio.create_task(check_connection())

    visible = asyncio.run(run())
    assert visible is False, (
        "Connection from a completed task should not be visible to a new task"
    )


def test_executor_sees_connection_with_context_propagation():
    """
    With explicit context propagation (contextvars.copy_context().run()),
    an executor thread should see the same connection as the caller.

    This validates the mechanism asyncio.to_thread() uses (it copies context
    automatically), which enables future SSE views to access the DB.
    """

    async def run() -> tuple[bool, int, int | None]:
        conn = _store_fake()
        caller_id = id(conn)

        executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        loop = asyncio.get_running_loop()
        ctx = contextvars.copy_context()

        def check_in_thread() -> tuple[bool, int | None]:
            has = has_connection()
            if has:
                return has, id(_db_conn.get())
            return has, None

        # Run with context propagation
        has_conn, thread_id = await loop.run_in_executor(
            executor, lambda: ctx.run(check_in_thread)
        )
        executor.shutdown(wait=True)
        return has_conn, caller_id, thread_id

    has_conn, caller_id, thread_id = asyncio.run(run())
    assert has_conn is True, "Executor thread should see the connection via context"
    assert caller_id == thread_id, (
        "Executor thread should see the same connection instance"
    )


def test_executor_without_context_does_not_see_connection():
    """
    Raw `loop.run_in_executor` does not propagate the caller's
    ContextVar context. Documented here as a sanity check on the
    asyncio mechanics that `BaseHandler._run_in_executor` builds on top
    of (the framework wraps each request in its own copied context to
    propagate state across executor hops).
    """

    async def run() -> bool:
        _store_fake()
        assert has_connection()

        executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        loop = asyncio.get_running_loop()

        # Run WITHOUT context propagation
        has_conn = await loop.run_in_executor(executor, has_connection)
        executor.shutdown(wait=True)
        return has_conn

    has_conn = asyncio.run(run())
    assert has_conn is False, (
        "Executor thread without context propagation should not see the connection"
    )


def test_executor_connection_persists_across_calls_on_same_thread():
    """
    Asyncio's ThreadPoolExecutor worker threads maintain a persistent
    ContextVar context across work items — a value set in one
    `loop.run_in_executor` call is visible to the next call that lands
    on the same thread.

    The framework opts out of this thread-level persistence by passing
    a per-request context to `BaseHandler._run_in_executor` (via
    `ctx.run`). This test documents the underlying asyncio behavior the
    framework is overriding.
    """

    async def run() -> tuple[int, int, int, int]:
        executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        loop = asyncio.get_running_loop()

        def request_1() -> tuple[int, int]:
            conn = FakeConn()
            _db_conn.set(conn)  # ty: ignore[invalid-argument-type]
            return threading.get_ident(), id(conn)

        def request_2() -> tuple[int, int]:
            val = _db_conn.get()
            return threading.get_ident(), id(val) if val is not None else -1

        tid1, conn_id1 = await loop.run_in_executor(executor, request_1)
        tid2, conn_id2 = await loop.run_in_executor(executor, request_2)
        executor.shutdown(wait=True)
        return tid1, tid2, conn_id1, conn_id2

    tid1, tid2, conn_id1, conn_id2 = asyncio.run(run())
    assert tid1 == tid2, "Both calls should run on the same executor thread"
    assert conn_id1 == conn_id2, (
        "Connection set in request 1 should persist for request 2 on the same thread"
    )
