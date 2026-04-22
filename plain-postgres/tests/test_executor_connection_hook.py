"""Pooled connections held by worker-thread ContextVar state are returned
to the pool.

When user code does DB work via `asyncio.to_thread(fn)`, `fn` runs in a
copied context (`contextvars.copy_context().run(fn)`). A `DatabaseConnection`
created inside that context lives only inside the copy — when the copy is
discarded, the wrapper's `__del__` fires and returns the pooled psycopg
connection back to the pool. Without this safety net, connections stay
checked out forever, since `request_finished` fires on the handler thread
and can't see the worker thread's ContextVar state.
"""

from __future__ import annotations

import asyncio
from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import pytest

from plain.postgres.db import _db_conn, get_connection
from plain.postgres.sources import runtime_pool_source


@pytest.fixture
def _fresh_pool() -> Generator[None]:
    runtime_pool_source.close()
    yield
    runtime_pool_source.close()


def _run_db_query() -> int:
    with get_connection().cursor() as cursor:
        cursor.execute("SELECT 1")
        row = cursor.fetchone()
        assert row is not None
        return row[0]


def _run_concurrent(n: int) -> None:
    """Run N concurrent DB queries via asyncio.to_thread + a fresh executor.

    Resets `_db_conn` so each to_thread's context copy starts with None
    instead of inheriting the test-suite's shared DirectSource wrapper.
    """
    import gc

    token = _db_conn.set(None)
    try:
        executor = ThreadPoolExecutor(max_workers=4)
        try:
            loop = asyncio.new_event_loop()
            try:
                loop.set_default_executor(executor)

                async def run() -> None:
                    tasks = [asyncio.to_thread(_run_db_query) for _ in range(n)]
                    results = await asyncio.gather(*tasks)
                    assert all(r == 1 for r in results)

                loop.run_until_complete(run())
            finally:
                loop.close()
        finally:
            executor.shutdown(wait=True)
    finally:
        _db_conn.reset(token)

    gc.collect()


@pytest.mark.usefixtures("_unblock_cursor", "_fresh_pool")
def test_many_to_thread_queries_do_not_deplete_pool(setup_db: Any) -> None:
    """50 sequential batches of 4 concurrent `asyncio.to_thread(db_query)` calls.

    Total checkouts = 200. Pool `max_size = 20`. Completing without
    `PoolTimeout` proves each wrapper's `__del__` returned its connection
    when the context copy was GC'd.
    """
    for _ in range(50):
        _run_concurrent(n=4)


@pytest.mark.usefixtures("_unblock_cursor", "_fresh_pool")
def test_direct_executor_submit_holds_connection(setup_db: Any) -> None:
    """Direct `executor.submit(db_query)` — no `copy_context`, no Plain
    pipeline, no `request_finished`.

    The wrapper lives in the worker thread's NATIVE ContextVar state, so it
    persists across calls and the connection stays checked out until the
    thread dies. Not a real code path — documents the shape that would
    leak if anyone did it.
    """
    executor = ThreadPoolExecutor(max_workers=1)
    try:
        fut = executor.submit(_run_db_query)
        assert fut.result() == 1
        stats = runtime_pool_source._get_pool().get_stats()
        held = stats.get("pool_size", 0) - stats.get("pool_available", 0)
        assert held >= 1, f"Expected worker to hold its connection, stats={stats}"
    finally:
        executor.shutdown(wait=True)
