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


def test_signal_exit_mid_iteration_shuts_down_cleanly() -> None:
    listener = _Listener()
    worker = Worker(
        age=0,
        ppid=os.getppid(),
        sockets=[listener],  # ty: ignore[invalid-argument-type]
        app=_StubApp(),  # ty: ignore[invalid-argument-type]
        timeout=5,
        heartbeat=None,  # ty: ignore[invalid-argument-type]
        handler=None,
    )

    capture = _CaptureHandler()
    logger = logging.getLogger("test.server.worker.shutdown")
    logger.addHandler(capture)
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    worker.log = logger

    # Normally created in init_process(), which this test bypasses.
    worker.tpool = ThreadPoolExecutor(max_workers=1)

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
