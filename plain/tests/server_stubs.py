"""Shared stand-ins for driving server Worker code directly in tests.

Used by the test_server_* internal tests, which construct a real Worker
without a listener, signals, or init_process().
"""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from plain.server.workers.worker import Worker


class StubApp:
    """Minimal stand-in for ServerApplication."""

    is_ssl = False
    certfile = None
    keyfile = None
    threads = 1
    reload = False


class StubHeartbeat:
    """Minimal stand-in for WorkerHeartbeat."""

    def __init__(self, *, deadline: float = 0.0) -> None:
        self.deadline = deadline

    def notify(self) -> None:
        pass

    def is_retiring(self) -> bool:
        return False

    def kill_deadline(self) -> float:
        return self.deadline


def make_worker(
    *,
    sockets: list[Any] | None = None,
    heartbeat: StubHeartbeat | None = None,
    handler: Any = None,
) -> Worker:
    worker = Worker(
        age=0,
        ppid=os.getppid(),
        sockets=sockets or [],
        app=StubApp(),  # ty: ignore[invalid-argument-type]
        timeout=5,
        heartbeat=heartbeat or StubHeartbeat(),  # ty: ignore[invalid-argument-type]
        handler=handler,
    )
    # Normally created in init_process(), which these tests bypass.
    worker.tpool = ThreadPoolExecutor(max_workers=1)
    return worker
