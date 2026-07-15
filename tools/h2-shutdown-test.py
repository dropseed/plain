"""H2 graceful shutdown behavior test.

Asserts the SIGTERM contract of `plain server` over TLS+HTTP/2: an open
connection receives GOAWAY and closes promptly (instead of parking in the
H2 idle timeout until the drain deadline cancels it), the master exits
cleanly, and nothing is logged at ERROR. Stream-level drain semantics
(REFUSED_STREAM for new streams, in-flight completion) are pinned by
plain/tests/internal/test_server_h2_shutdown.py.

The phases are sequential and share the server process, so this script
needs to own it. Run via ./tools/h2-shutdown-test:

    ./tools/h2-shutdown-test
"""

from __future__ import annotations

import argparse
import os
import signal
import socket
import ssl
import subprocess
import sys
import time
from collections.abc import Callable
from typing import Any

import h2.config
import h2.connection
import h2.events

# ---------------------------------------------------------------------------
# Colors
# ---------------------------------------------------------------------------
GREEN = "\033[32m"
RED = "\033[31m"
BOLD = "\033[1m"
DIM = "\033[2m"
RESET = "\033[0m"


def create_h2_connection(
    addr: tuple[str, int],
) -> tuple[ssl.SSLSocket, h2.connection.H2Connection]:
    """Create a TLS+h2 connection to the server."""
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    ctx.set_alpn_protocols(["h2"])

    raw_sock = socket.create_connection(addr, timeout=10)
    tls_sock = ctx.wrap_socket(raw_sock, server_hostname=addr[0])

    assert tls_sock.selected_alpn_protocol() == "h2", (
        f"Expected h2 ALPN, got {tls_sock.selected_alpn_protocol()}"
    )

    config = h2.config.H2Configuration(client_side=True, header_encoding="utf-8")
    conn = h2.connection.H2Connection(config=config)
    conn.initiate_connection()
    tls_sock.sendall(conn.data_to_send())

    return tls_sock, conn


def send_request(
    conn: h2.connection.H2Connection,
    sock: ssl.SSLSocket,
    path: str = "/",
) -> int:
    stream_id = conn.get_next_available_stream_id()
    conn.send_headers(
        stream_id,
        [
            (":method", "GET"),
            (":path", path),
            (":authority", "localhost"),
            (":scheme", "https"),
        ],
        end_stream=True,
    )
    sock.sendall(conn.data_to_send())
    return stream_id


def read_events(
    conn: h2.connection.H2Connection,
    sock: ssl.SSLSocket,
    done: Callable[[list[h2.events.Event]], bool],
    timeout: float = 10.0,
) -> tuple[list[h2.events.Event], bool]:
    """Read frames until done(events) is true or the socket closes.

    Returns (events, eof).
    """
    events: list[h2.events.Event] = []
    deadline = time.monotonic() + timeout
    sock.settimeout(1.0)

    while time.monotonic() < deadline and not done(events):
        try:
            data = sock.recv(65535)
        except TimeoutError:
            continue
        except OSError:
            return events, True
        if not data:
            return events, True
        events.extend(conn.receive_data(data))
        acks = conn.data_to_send()
        if acks:
            try:
                sock.sendall(acks)
            except OSError:
                return events, True

    return events, False


def process_exited(pid: int) -> bool:
    """True once the process is gone (or a zombie awaiting reap by our parent)."""
    result = subprocess.run(
        ["ps", "-p", str(pid), "-o", "stat="],
        capture_output=True,
        text=True,
    )
    stat = result.stdout.strip()
    return not stat or stat.startswith("Z")


# ---------------------------------------------------------------------------
# Phases (sequential — each depends on the previous)
# ---------------------------------------------------------------------------


def test_h2_request_before_sigterm(
    sock: ssl.SSLSocket, conn: h2.connection.H2Connection
) -> bool | tuple[bool, str]:
    """A request completes over TLS+h2 before the signal."""
    stream_id = send_request(conn, sock)
    events, eof = read_events(
        conn,
        sock,
        lambda evs: any(
            isinstance(e, h2.events.StreamEnded) and e.stream_id == stream_id
            for e in evs
        ),
    )
    if eof:
        return False, "Connection closed before response"
    for event in events:
        if isinstance(event, h2.events.ResponseReceived):
            return True
    return False, f"No response received: {events}"


def test_goaway_on_sigterm(
    sock: ssl.SSLSocket, conn: h2.connection.H2Connection, pid: int
) -> bool | tuple[bool, str]:
    """An open connection receives GOAWAY and closes promptly at SIGTERM."""
    os.kill(pid, signal.SIGTERM)

    events, eof = read_events(
        conn,
        sock,
        lambda evs: any(isinstance(e, h2.events.ConnectionTerminated) for e in evs),
        timeout=10.0,
    )
    terminated = any(isinstance(e, h2.events.ConnectionTerminated) for e in events)
    if not terminated:
        detail = "connection closed without GOAWAY" if eof else f"no GOAWAY: {events}"
        return False, detail

    if not eof:
        _, eof = read_events(conn, sock, lambda evs: False, timeout=5.0)
        if not eof:
            return False, "Server sent GOAWAY but never closed the connection"
    return True


def test_master_exits(pid: int) -> bool | tuple[bool, str]:
    """Master process exits well inside the graceful timeout."""
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if process_exited(pid):
            return True
        time.sleep(0.2)
    return False, "Master still running 15s after SIGTERM"


def test_no_errors_logged(log_path: str) -> bool | tuple[bool, str]:
    """A normal shutdown logs nothing at ERROR and no tracebacks."""
    with open(log_path, "rb") as f:
        log = f.read().decode("utf-8", errors="replace")
    if "Plain server started" not in log:
        return False, "Captured log missing 'Plain server started' line"
    for line in log.splitlines():
        if "ERROR" in line or "Traceback" in line:
            return False, f"Unexpected error output: {line.strip()}"
    return True


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description="H2 graceful shutdown behavior test")
    parser.add_argument("target", help="host:port of the TLS server to test")
    parser.add_argument("--pid", type=int, required=True, help="Server master PID")
    parser.add_argument("--log", required=True, help="File capturing server output")
    args = parser.parse_args()

    host, port_str = args.target.rsplit(":", 1)
    addr = (host, int(port_str))

    sock, conn = create_h2_connection(addr)

    tests: list[tuple[str, Callable[[], Any]]] = [
        (
            "H2 request completes before SIGTERM",
            lambda: test_h2_request_before_sigterm(sock, conn),
        ),
        (
            "Open connection gets GOAWAY and closes",
            lambda: test_goaway_on_sigterm(sock, conn, args.pid),
        ),
        ("Master exits within 15s", lambda: test_master_exits(args.pid)),
        ("No errors logged during shutdown", lambda: test_no_errors_logged(args.log)),
    ]

    print(f"\n{BOLD}H2 Graceful Shutdown Behavior{RESET}\n")

    passed = 0
    failed = 0

    for i, (name, fn) in enumerate(tests, 1):
        try:
            result = fn()
            if isinstance(result, tuple):
                ok, detail = result
            else:
                ok = result
                detail = ""
        except Exception as e:
            ok = False
            detail = f"Exception: {e}"

        if ok:
            passed += 1
            print(f"  {GREEN}✓{RESET} {i}. {name}")
        else:
            failed += 1
            print(f"  {RED}✗{RESET} {i}. {name}")
            if detail:
                print(f"      {DIM}{detail}{RESET}")

    sock.close()

    print()
    total = passed + failed
    if failed == 0:
        print(f"{GREEN}{passed}/{total} passed{RESET}")
    else:
        print(f"{RED}{passed}/{total} passed, {failed} failed{RESET}")

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
