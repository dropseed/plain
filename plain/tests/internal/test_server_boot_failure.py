"""A worker that fails to boot in reload mode must not take down the dev
stack — worker_main runs serve_boot_failure instead of exiting with
WORKER_BOOT_ERROR, so the arbiter never halts and poncho never group-kills.

This pins the stand-in server itself: it accepts connections on the
inherited (non-blocking) listener socket, responds 500 with the boot
traceback, keeps the heartbeat fresh, and returns once the reloader
reports a file change so the process can recycle with fresh code.
"""

from __future__ import annotations

import os
import signal
import socket
import threading

from plain.server.workers import boot_failure
from server_stubs import StubApp


class _StubHeartbeat:
    def __init__(self) -> None:
        self.notifies = 0

    def notify(self) -> None:
        self.notifies += 1


def test_serves_traceback_then_returns_on_file_change(monkeypatch) -> None:
    captured: dict = {}

    class FakeReloader:
        def __init__(self, callback, watch_html) -> None:
            captured["callback"] = callback

        def start(self) -> None:
            pass

    monkeypatch.setattr(boot_failure, "Reloader", FakeReloader)

    # Mimic an inherited listener: bound, listening, non-blocking.
    listener = socket.create_server(("127.0.0.1", 0))
    listener.setblocking(False)
    port = listener.getsockname()[1]

    results: dict = {}

    def request(raw: bytes) -> bytes:
        # The kernel queues the connection until the loop accepts it,
        # so no startup synchronization is needed.
        with socket.create_connection(("127.0.0.1", port), timeout=5) as conn:
            conn.settimeout(5)
            conn.sendall(raw)
            return conn.makefile("rb").read()

    def client() -> None:
        try:
            results["text"] = request(b"GET / HTTP/1.1\r\nHost: test\r\n\r\n")
            results["html"] = request(
                b"GET / HTTP/1.1\r\nHost: test\r\nAccept: text/html\r\n\r\n"
            )
            # text/html anywhere else in the request must not count.
            results["not_accept"] = request(
                b"POST / HTTP/1.1\r\nHost: test\r\n"
                b"Content-Type: text/html\r\nContent-Length: 0\r\n\r\n"
            )
        finally:
            # Fire the reloader callback even if the reads failed, so a
            # broken serve loop fails the assertions instead of hanging
            # the suite on a loop that never returns.
            captured["callback"]("app/broken.py")  # the fix gets saved

    client_thread = threading.Thread(target=client)
    client_thread.start()

    heartbeat = _StubHeartbeat()
    # serve_boot_failure installs signal handlers; restore pytest's.
    handled_signals = (
        signal.SIGTERM,
        signal.SIGINT,
        signal.SIGQUIT,
        signal.SIGABRT,
        signal.SIGUSR1,
    )
    saved_handlers = {sig: signal.getsignal(sig) for sig in handled_signals}
    try:
        boot_failure.serve_boot_failure(
            listeners=[listener],  # ty: ignore[invalid-argument-type]
            app=StubApp(),  # ty: ignore[invalid-argument-type]
            heartbeat=heartbeat,  # ty: ignore[invalid-argument-type]
            arbiter_pid=os.getppid(),
            traceback_text="ImportError: cannot import name 'X'",
        )
    finally:
        for sig, handler in saved_handlers.items():
            signal.signal(sig, handler)
        client_thread.join(timeout=5)
        listener.close()

    text = results["text"]
    assert text.startswith(b"HTTP/1.1 500 ")
    assert b"Content-Type: text/plain" in text
    assert b"ImportError: cannot import name 'X'" in text

    # Browsers get an HTML page that refreshes itself, so the tab
    # recovers on its own once the fix lands and the worker recycles.
    html = results["html"]
    assert html.startswith(b"HTTP/1.1 500 ")
    assert b"Content-Type: text/html" in html
    assert b'<meta http-equiv="refresh"' in html
    assert b"ImportError: cannot import name &#x27;X&#x27;" in html

    # Only the Accept header selects HTML — a text/html Content-Type
    # elsewhere in the request still gets the plain-text variant.
    assert b"Content-Type: text/plain" in results["not_accept"]

    assert heartbeat.notifies >= 1
