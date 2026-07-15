"""H1 graceful shutdown behavior test.

Asserts the SIGTERM contract of `plain server` over HTTP/1.1: an in-flight
request drains with `Connection: close`, the master process exits promptly,
and nothing is logged at ERROR during a normal shutdown (a regression guard —
a deploy-time SIGTERM once produced a spurious "Server stopped serving
unexpectedly" error from the worker heartbeat loop; the deterministic pin for
that race is plain/tests/internal/test_server_worker_shutdown.py, this suite
covers the user-visible contract). H2 shutdown is covered by
tools/h2-shutdown-test and plain/tests/internal/test_server_h2_shutdown.py.

The phases are sequential and share the server process, so this script
needs to own it. Run via ./tools/shutdown-test:

    ./tools/shutdown-test
"""

from __future__ import annotations

import argparse
import os
import re
import signal
import socket
import subprocess
import sys
import time
from collections.abc import Callable
from typing import Any

# ---------------------------------------------------------------------------
# Colors
# ---------------------------------------------------------------------------
GREEN = "\033[32m"
RED = "\033[31m"
BOLD = "\033[1m"
DIM = "\033[2m"
RESET = "\033[0m"

_STATUS_RE = re.compile(rb"HTTP/\d\.\d\s+(\d{3})")


def connect(addr: tuple[str, int]) -> socket.socket:
    return socket.create_connection(addr, timeout=5)


def parse_status(data: bytes) -> int:
    m = _STATUS_RE.search(data)
    return int(m.group(1)) if m else 0


def recv_response(s: socket.socket) -> bytes:
    """Read one full HTTP response (headers + Content-Length body)."""
    buf = b""
    while b"\r\n\r\n" not in buf:
        chunk = s.recv(4096)
        if not chunk:
            return buf
        buf += chunk

    header_blob, rest = buf.split(b"\r\n\r\n", 1)

    cl = None
    for line in header_blob.split(b"\r\n")[1:]:
        if line.lower().startswith(b"content-length:"):
            cl = int(line.split(b":", 1)[1].strip())
            break

    if cl is not None:
        while len(rest) < cl:
            chunk = s.recv(4096)
            if not chunk:
                break
            rest += chunk
        return header_blob + b"\r\n\r\n" + rest[:cl]

    return buf


def recv_until_closed(s: socket.socket, *, deadline: float = 10.0) -> bytes:
    """Read until the server closes the connection.

    The drained response must be followed by an actual close, so a server
    that goes quiet without closing is a failure — raise instead of
    returning partial data. A reset still counts as closed (we assert on
    whatever was delivered).
    """
    buf = b""
    end = time.monotonic() + deadline
    while True:
        remaining = end - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("Server did not close the connection")
        s.settimeout(remaining)
        try:
            chunk = s.recv(4096)
        except TimeoutError:
            raise TimeoutError("Server did not close the connection") from None
        except OSError:
            return buf
        if not chunk:
            return buf
        buf += chunk


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


def test_serving_before_sigterm(addr: tuple[str, int]) -> bool | tuple[bool, str]:
    """Server responds normally before the signal."""
    s = connect(addr)
    s.settimeout(5)
    try:
        # The example app sets HEALTHCHECK_PATH = "/up/"
        s.sendall(b"GET /up/ HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n")
        status = parse_status(recv_until_closed(s))
        if status != 200:
            return False, f"Expected 200, got {status}"
        return True
    finally:
        s.close()


def test_inflight_drains(addr: tuple[str, int], pid: int) -> bool | tuple[bool, str]:
    """A request in flight at SIGTERM completes and is told to close."""
    body = b"x" * 1024
    s = connect(addr)
    s.settimeout(10)
    # Second connection, established before the signal, used to observe
    # when the worker has actually seen the SIGTERM.
    probe = connect(addr)
    probe.settimeout(5)
    try:
        # Start a request but hold back the body so it is mid-read inside
        # the worker when the signal lands. Expect: 100-continue makes the
        # worker acknowledge it has accepted and parsed the request before
        # we signal — otherwise the bytes could still be sitting in the
        # listener backlog when SIGTERM closes it.
        s.sendall(
            b"POST / HTTP/1.1\r\n"
            b"Host: localhost\r\n"
            b"Content-Type: application/octet-stream\r\n"
            b"Content-Length: " + str(len(body)).encode() + b"\r\n"
            b"Expect: 100-continue\r\n"
            b"\r\n"
        )
        interim = recv_response(s)
        if parse_status(interim) != 100:
            return False, f"Expected 100 Continue, got {interim[:100]!r}"

        os.kill(pid, signal.SIGTERM)

        # Wait until the worker has observed the SIGTERM rather than
        # guessing with a fixed sleep: once the worker starts shutting
        # down, dispatched keep-alive responses switch to Connection: close.
        # (Probe / rather than /up/ — the healthcheck is answered at the
        # server layer, outside the dispatch path that adds the header.)
        deadline = time.monotonic() + 10
        while True:
            if time.monotonic() > deadline:
                return False, "Worker never switched to Connection: close"
            try:
                probe.sendall(b"GET / HTTP/1.1\r\nHost: localhost\r\n\r\n")
                resp = recv_response(probe)
            except OSError:
                # The keep-alive loop exits once the worker stops, so a
                # torn-down probe also means shutdown was observed.
                break
            if not resp:
                break
            if b"connection: close" in resp.split(b"\r\n\r\n", 1)[0].lower():
                break
            time.sleep(0.1)

        s.sendall(body)
        resp = recv_until_closed(s)

        # POST / deterministically returns 301 (the framework's HTTPS
        # redirect middleware, before any app view or DB access). Pinning
        # it proves the request completed rather than being rejected with
        # a shutdown 5xx.
        status = parse_status(resp)
        if status != 301:
            return False, f"Expected 301 drained response, got {status or resp[:100]!r}"
        headers = resp.split(b"\r\n\r\n", 1)[0].lower()
        if b"connection: close" not in headers:
            return False, "Drained response missing Connection: close"
        return True
    finally:
        probe.close()
        s.close()


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
    # Positive control: prove the capture worked and the log format still
    # carries the lines we grep, so a capture or format change can't
    # silently disarm this check.
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
    parser = argparse.ArgumentParser(description="H1 graceful shutdown behavior test")
    parser.add_argument("target", help="host:port of the server to test")
    parser.add_argument("--pid", type=int, required=True, help="Server master PID")
    parser.add_argument("--log", required=True, help="File capturing server output")
    args = parser.parse_args()

    host, port_str = args.target.rsplit(":", 1)
    addr = (host, int(port_str))

    tests: list[tuple[str, Callable[[], Any]]] = [
        ("Server responds before SIGTERM", lambda: test_serving_before_sigterm(addr)),
        (
            "In-flight request drains with Connection: close",
            lambda: test_inflight_drains(addr, args.pid),
        ),
        ("Master exits within 15s", lambda: test_master_exits(args.pid)),
        ("No errors logged during shutdown", lambda: test_no_errors_logged(args.log)),
    ]

    print(f"\n{BOLD}H1 Graceful Shutdown Behavior{RESET}\n")

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

    print()
    total = passed + failed
    if failed == 0:
        print(f"{GREEN}{passed}/{total} passed{RESET}")
    else:
        print(f"{RED}{passed}/{total} passed, {failed} failed{RESET}")

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
