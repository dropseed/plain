from __future__ import annotations

import contextlib
import os
import select
import signal
import socket
import ssl
import threading
import time
from typing import TYPE_CHECKING

from plain.internal.reloader import Reloader

from ..sock import ssl_context

if TYPE_CHECKING:
    from ..app import ServerApplication
    from ..sock import BaseSocket
    from .workertmp import WorkerHeartbeat

# How long to serve the error before recycling for a fresh boot attempt
# anyway. The reloader can't see every fix — external state (a database
# coming back up) or an editable package outside the watched paths — so
# recycling on an interval bounds how stale the stand-in can get.
RETRY_BOOT_SECONDS = 60


def serve_boot_failure(
    *,
    listeners: list[BaseSocket],
    app: ServerApplication,
    heartbeat: WorkerHeartbeat,
    traceback_text: str,
) -> None:
    """Stand in for a worker that failed to boot, until the code changes again.

    Reload mode only. Instead of exiting with a boot error code (which halts
    the arbiter and takes the whole dev stack down with it), the worker
    process stays alive: it keeps heartbeating so the arbiter leaves it
    alone, serves the boot traceback as a 500 on the inherited listener
    sockets, and returns — so the process can exit cleanly and be respawned
    with freshly imported code — on the next file change, or after
    RETRY_BOOT_SECONDS, or if the arbiter dies.

    Deliberately avoids settings and the runtime — plain.runtime.setup()
    may be exactly what failed.
    """
    stop = threading.Event()

    # The arbiter's shutdown paths signal workers (SIGTERM graceful,
    # SIGQUIT hard stop, SIGINT from Ctrl-C in the foreground process
    # group) — exit cleanly on all of them instead of dying with a
    # KeyboardInterrupt traceback or a core dump.
    for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGQUIT):
        signal.signal(sig, lambda signum, frame: stop.set())

    # The reloader derives watch paths from sys.modules, which is only
    # partially populated after a failed boot — the cwd, watched
    # recursively, is what covers the app code here. Fixes outside the
    # watched paths are picked up by the RETRY_BOOT_SECONDS recycle.
    reloader = Reloader(callback=lambda fname: stop.set(), watch_html=True)
    reloader.start()

    tls_context: ssl.SSLContext | None = None
    if app.is_ssl:
        assert app.certfile is not None
        tls_context = ssl_context(app.certfile, app.keyfile)
        # This loop only speaks HTTP/1.1 — don't offer h2 in ALPN.
        tls_context.set_alpn_protocols(["http/1.1"])

    body = (
        "Worker failed to boot. Serving this error until the code changes.\n\n"
        + traceback_text
    ).encode("utf-8", errors="replace")
    head = (
        "HTTP/1.1 500 Internal Server Error\r\n"
        "Connection: close\r\n"
        "Content-Type: text/plain; charset=utf-8\r\n"
        f"Content-Length: {len(body)}\r\n"
        "\r\n"
    )
    response = head.encode("ascii") + body

    ppid = os.getppid()
    deadline = time.monotonic() + RETRY_BOOT_SECONDS

    while not stop.is_set():
        heartbeat.notify()
        if os.getppid() != ppid:
            return  # The arbiter died without SIGTERM — don't linger as an orphan.
        if time.monotonic() > deadline:
            return  # Recycle for a fresh boot attempt.
        ready, _, _ = select.select(listeners, [], [], 1.0)
        for listener in ready:
            try:
                conn, _addr = listener.accept()
            except OSError:
                continue
            # A thread per connection, so an idle browser preconnect or a
            # slow client can't stall the response to the next request.
            threading.Thread(
                target=_respond_and_close,
                args=(conn, tls_context, response),
                daemon=True,
            ).start()


def _respond_and_close(
    conn: socket.socket, tls_context: ssl.SSLContext | None, response: bytes
) -> None:
    try:
        conn.settimeout(1)
        if tls_context:
            conn = tls_context.wrap_socket(conn, server_side=True)
        conn.recv(65536)  # The response is the same regardless of the request.
        conn.sendall(response)
        # Closing with unread request data (a POST body) still in the
        # buffer makes the kernel send RST, which discards the response
        # before the client reads it. Half-close and drain instead.
        conn.shutdown(socket.SHUT_WR)
        while conn.recv(65536):
            pass
    except Exception:
        pass  # Port scans, aborted handshakes, timeouts — connection noise.
    finally:
        with contextlib.suppress(OSError):
            conn.close()
