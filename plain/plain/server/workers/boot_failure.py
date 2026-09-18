from __future__ import annotations

import contextlib
import html
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

# At most this many responder threads at once — extra connections are
# dropped. The stand-in is deliberately dumb about concurrency.
MAX_RESPONDER_THREADS = 32


def serve_boot_failure(
    *,
    listeners: list[BaseSocket],
    app: ServerApplication,
    heartbeat: WorkerHeartbeat,
    arbiter_pid: int,
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
    # group, SIGABRT from a heartbeat timeout) — exit cleanly on all of
    # them instead of dying with a traceback or a core dump.
    for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGQUIT, signal.SIGABRT):
        signal.signal(sig, lambda signum, frame: stop.set())
    # The arbiter forwards SIGUSR1 to workers for memory reports; there is
    # nothing to report here, and the default disposition would kill us.
    signal.signal(signal.SIGUSR1, signal.SIG_IGN)

    # The reloader derives watch paths from sys.modules, which is only
    # partially populated after a failed boot — the cwd, watched
    # recursively, is what covers the app code here. Fixes outside the
    # watched paths are picked up by the RETRY_BOOT_SECONDS recycle.
    reloader = Reloader(callback=lambda fname: stop.set(), watch_html=True)
    reloader.start()

    tls_context: ssl.SSLContext | None = None
    if app.certfile:
        tls_context = ssl_context(app.certfile, app.keyfile)
        # This loop only speaks HTTP/1.1 — don't offer h2 in ALPN.
        tls_context.set_alpn_protocols(["http/1.1"])

    # Two variants of the same response: plain text for curl/agents, and
    # HTML with a meta refresh for browsers — so the tab reloads itself
    # into the working app once a fix lands and the worker recycles.
    text_response = _build_response(
        content_type="text/plain; charset=utf-8",
        body_text=(
            "Worker failed to boot. Serving this error until the code changes.\n\n"
            + traceback_text
        ),
    )
    html_response = _build_response(
        content_type="text/html; charset=utf-8",
        body_text=(
            "<!doctype html>\n"
            "<html>\n"
            "  <head>\n"
            '    <meta http-equiv="refresh" content="2">\n'
            "    <title>Worker failed to boot</title>\n"
            "  </head>\n"
            "  <body>\n"
            "    <h1>Worker failed to boot</h1>\n"
            "    <p>Serving this error until the code changes."
            " This page refreshes automatically.</p>\n"
            f"    <pre>{html.escape(traceback_text)}</pre>\n"
            "  </body>\n"
            "</html>\n"
        ),
    )

    deadline = time.monotonic() + RETRY_BOOT_SECONDS
    responders: list[threading.Thread] = []

    while not stop.is_set():
        heartbeat.notify()
        if os.getppid() != arbiter_pid:
            break  # The arbiter died without SIGTERM — don't linger as an orphan.
        if time.monotonic() > deadline:
            break  # Recycle for a fresh boot attempt.
        ready, _, _ = select.select(listeners, [], [], 1.0)
        responders = [t for t in responders if t.is_alive()]
        for listener in ready:
            try:
                conn, _addr = listener.accept()
            except OSError:
                continue
            # A thread per connection, so an idle browser preconnect or a
            # slow client can't stall the response to the next request.
            thread = threading.Thread(
                target=_respond_and_close,
                kwargs={
                    "conn": conn,
                    "tls_context": tls_context,
                    "text_response": text_response,
                    "html_response": html_response,
                },
                daemon=True,
            )
            if len(responders) >= MAX_RESPONDER_THREADS:
                with contextlib.suppress(OSError):
                    conn.close()
                continue
            try:
                thread.start()
            except RuntimeError:
                # Can't start a thread — drop the connection, keep serving.
                with contextlib.suppress(OSError):
                    conn.close()
                continue
            responders.append(thread)

    # Let in-flight responses finish sending and draining before the
    # process exits — dying mid-drain would RST the response away.
    join_deadline = time.monotonic() + 3
    for thread in responders:
        thread.join(timeout=max(0.0, join_deadline - time.monotonic()))


def _build_response(*, content_type: str, body_text: str) -> tuple[bytes, bytes]:
    """Returns (head, full). HEAD requests get only the header block —
    its Content-Length still describes the GET body (RFC 9110 9.3.2)."""
    body = body_text.encode("utf-8", errors="replace")
    head = (
        "HTTP/1.1 500 Internal Server Error\r\n"
        "Connection: close\r\n"
        f"Content-Type: {content_type}\r\n"
        f"Content-Length: {len(body)}\r\n"
        "\r\n"
    ).encode("ascii")
    return head, head + body


def _recv_head(*, conn: socket.socket, deadline: float) -> bytes:
    """Read until the end of the request headers (bounded by size and time)."""
    data = b""
    while b"\r\n\r\n" not in data and len(data) < 65536 and time.monotonic() < deadline:
        chunk = conn.recv(65536)
        if not chunk:
            break
        data += chunk
    return data


def _wants_html(request: bytes) -> bool:
    """True when the Accept header asks for text/html (i.e. a browser)."""
    head = request.split(b"\r\n\r\n", 1)[0]
    for line in head.split(b"\r\n")[1:]:
        if line.lower().startswith(b"accept:"):
            return b"text/html" in line.lower()
    return False


def _respond_and_close(
    *,
    conn: socket.socket,
    tls_context: ssl.SSLContext | None,
    text_response: tuple[bytes, bytes],
    html_response: tuple[bytes, bytes],
) -> None:
    try:
        # One time budget for the whole exchange. Count caps alone would
        # let a client trickling bytes under the per-recv timeout hold a
        # responder thread for hours, while a fast large upload
        # legitimately needs many recvs.
        deadline = time.monotonic() + 10
        conn.settimeout(1)
        if tls_context:
            conn = tls_context.wrap_socket(conn, server_side=True)
        request = _recv_head(conn=conn, deadline=deadline)
        head, full = html_response if _wants_html(request) else text_response
        conn.sendall(head if request.startswith(b"HEAD ") else full)
        # Closing with unread request data (a POST body) still in the
        # buffer makes the kernel send RST, which discards the response
        # before the client reads it. Half-close and drain until the
        # client finishes or the budget runs out.
        conn.shutdown(socket.SHUT_WR)
        while time.monotonic() < deadline:
            if not conn.recv(65536):
                break
    except Exception:
        pass  # Port scans, aborted handshakes, timeouts — connection noise.
    finally:
        with contextlib.suppress(OSError):
            conn.close()
