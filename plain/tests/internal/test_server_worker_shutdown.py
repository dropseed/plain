"""Worker shutdown must stay clean when servers close mid-iteration.

The SIGTERM handler (Worker._signal_exit) runs as an event-loop callback,
so it can close the listener servers between any two awaits of the
heartbeat loop in Worker.run(). A per-tick check on server state would see
the closed servers and report a crash during a normal shutdown — that
false positive shipped to production once ("Server stopped serving
unexpectedly" logged at ERROR on every deploy that hit the window).

This test pins the constraint deterministically: it triggers _signal_exit
at the top of a heartbeat tick (via notify(), which runs before the rest
of the tick body) and asserts the worker exits cleanly without logging
anything at ERROR. The socket-level contract (drain, exit code, log
output) is covered by tools/shutdown-test.
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import socket
import time
from concurrent.futures import ThreadPoolExecutor

from plain.server.workers.worker import Worker


class _Listener:
    """Minimal stand-in for sock.BaseSocket — run() only reads .sock."""

    def __init__(self) -> None:
        self.sock: socket.socket | None = socket.create_server(("127.0.0.1", 0))


class _StubApp:
    """Minimal stand-in for ServerApplication."""

    is_ssl = False
    certfile = None
    keyfile = None
    threads = 1
    reload = False


class _CaptureHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


def _make_worker(listener: _Listener | None = None) -> Worker:
    worker = Worker(
        age=0,
        ppid=os.getppid(),
        sockets=[listener] if listener else [],  # ty: ignore[invalid-argument-type]
        app=_StubApp(),  # ty: ignore[invalid-argument-type]
        timeout=5,
        heartbeat=None,  # ty: ignore[invalid-argument-type]
        handler=None,
    )
    # Normally created in init_process(), which these tests bypass.
    worker.tpool = ThreadPoolExecutor(max_workers=1)
    return worker


def test_signal_exit_mid_iteration_shuts_down_cleanly() -> None:
    listener = _Listener()
    worker = _make_worker(listener)

    capture = _CaptureHandler()
    logger = logging.getLogger("test.server.worker.shutdown")
    logger.addHandler(capture)
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    worker.log = logger

    # Simulate the race: notify() runs at the top of each heartbeat tick,
    # so closing the servers there means the rest of that tick's body runs
    # against already-closed servers — exactly what a SIGTERM landing
    # mid-iteration produces.
    worker.notify = worker._signal_exit  # ty: ignore[invalid-assignment]

    # run() installs process-level handlers for these; restore them so the
    # test doesn't leak signal state into the rest of the suite.
    saved = {s: signal.getsignal(s) for s in (signal.SIGABRT, signal.SIGWINCH)}
    try:
        asyncio.run(worker.run())
    finally:
        for sig, handler in saved.items():
            signal.signal(sig, handler)
        assert listener.sock is not None
        listener.sock.close()

    assert worker.alive is False
    errors = [r for r in capture.records if r.levelno >= logging.ERROR]
    assert errors == [], [r.getMessage() for r in errors]


def _drain(worker: Worker, *, task_seconds: float) -> tuple[bool, float]:
    """Run _graceful_shutdown with one in-flight task; return (completed, elapsed)."""

    async def scenario() -> tuple[bool, float]:
        completed = False

        async def in_flight() -> None:
            nonlocal completed
            await asyncio.sleep(task_seconds)
            completed = True

        task = asyncio.create_task(in_flight())
        worker._connection_tasks.add(task)
        await asyncio.sleep(0)  # let the task start
        start = time.monotonic()
        await worker._graceful_shutdown()
        return completed, time.monotonic() - start

    return asyncio.run(scenario())


def test_drain_notifies_heartbeat_and_completes_requests() -> None:
    worker = _make_worker()
    notifies = 0

    def notify() -> None:
        nonlocal notifies
        notifies += 1

    worker.notify = notify  # ty: ignore[invalid-assignment]

    completed, _ = _drain(worker, task_seconds=1.5)

    assert completed, "in-flight request should finish within the drain window"
    # One notify per drain slice — a draining worker must keep its
    # heartbeat fresh so the arbiter doesn't murder it mid-drain.
    assert notifies >= 2


def test_stalled_pool_drain_skips_heartbeat() -> None:
    worker = _make_worker()
    notifies = 0

    def notify() -> None:
        nonlocal notifies
        notifies += 1

    worker.notify = notify  # ty: ignore[invalid-assignment]
    # The stalled-thread-pool exit sets this so the arbiter still sees a
    # stale heartbeat and replaces the worker.
    worker._notify_during_drain = False

    completed, _ = _drain(worker, task_seconds=0.2)

    assert completed
    assert notifies == 0


def test_drain_deadline_anchored_at_sigterm_time() -> None:
    worker = _make_worker()
    worker.notify = lambda: None  # ty: ignore[invalid-assignment]
    # Simulate SIGTERM received long ago: the graceful budget is spent, so
    # the drain must cancel immediately rather than waiting a fresh full
    # SERVER_GRACEFUL_TIMEOUT (the arbiter's SIGKILL is imminent).
    worker._sigterm_time = time.monotonic() - 3600

    completed, elapsed = _drain(worker, task_seconds=30)

    assert not completed, "task should be cancelled, not awaited"
    assert elapsed < 2
