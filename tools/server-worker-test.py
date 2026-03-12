"""Server worker behavior tests.

Tests concurrency, keepalive lifecycle, slow clients, and request body
handling at the socket level. Run via ./tools/server-worker-test or directly:

    python tools/server-worker-test.py host:port [--threads N]

The --threads flag tells the test how many threads the server is running
so the exhaustion test can saturate the pool. Defaults to 4 (the Plain default).
"""

from __future__ import annotations

import argparse
import re
import socket
import sys
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

# ---------------------------------------------------------------------------
# Colors
# ---------------------------------------------------------------------------
GREEN = "\033[32m"
RED = "\033[31m"
BOLD = "\033[1m"
DIM = "\033[2m"
RESET = "\033[0m"

# ---------------------------------------------------------------------------
# Minimal HTTP client helpers
# ---------------------------------------------------------------------------

SIMPLE_GET = b"GET / HTTP/1.1\r\nHost: localhost\r\n\r\n"
CLOSE_GET = b"GET / HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n"

_STATUS_RE = re.compile(rb"HTTP/\d\.\d\s+(\d{3})")


def connect(addr: tuple[str, int]) -> socket.socket:
    return socket.create_connection(addr, timeout=5)


def parse_status(data: bytes) -> int:
    m = _STATUS_RE.search(data)
    return int(m.group(1)) if m else 0


def is_valid(status: int) -> bool:
    return 100 <= status <= 599


def recv_response(s: socket.socket) -> bytes:
    """Read one full HTTP response (headers + body)."""
    buf = b""
    # Read until we have the header section
    while b"\r\n\r\n" not in buf:
        chunk = s.recv(4096)
        if not chunk:
            return buf
        buf += chunk

    header_blob, rest = buf.split(b"\r\n\r\n", 1)

    # Parse Content-Length to know how much body to read
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

    # No content-length — check for chunked or just return what we have
    return header_blob + b"\r\n\r\n" + rest


def recv_close_response(s: socket.socket) -> bytes:
    """Read until server closes the connection."""
    chunks = []
    try:
        while chunk := s.recv(4096):
            chunks.append(chunk)
    except (TimeoutError, OSError):
        pass
    return b"".join(chunks)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_concurrent_connections(addr: tuple[str, int]) -> bool | tuple[bool, str]:
    """Server handles 10 simultaneous connections."""

    def do_request() -> int:
        s = connect(addr)
        s.settimeout(10)
        s.sendall(CLOSE_GET)
        resp = recv_close_response(s)
        s.close()
        return parse_status(resp)

    n = 10
    with ThreadPoolExecutor(max_workers=n) as pool:
        futs = [pool.submit(do_request) for _ in range(n)]
        statuses = [f.result() for f in as_completed(futs)]

    ok = sum(1 for s in statuses if is_valid(s))
    if ok == n:
        return True
    return False, f"{ok}/{n} got valid responses: {statuses}"


def test_concurrent_keepalive(addr: tuple[str, int]) -> bool | tuple[bool, str]:
    """Multiple connections each do 3 keep-alive requests."""

    def do_session() -> list[int]:
        s = connect(addr)
        s.settimeout(10)
        statuses = []
        for _ in range(3):
            s.sendall(SIMPLE_GET)
            resp = recv_response(s)
            statuses.append(parse_status(resp))
        s.close()
        return statuses

    n = 5
    with ThreadPoolExecutor(max_workers=n) as pool:
        futs = [pool.submit(do_session) for _ in range(n)]
        all_statuses = [f.result() for f in as_completed(futs)]

    total = sum(len(s) for s in all_statuses)
    ok = sum(1 for session in all_statuses for s in session if is_valid(s))
    if ok == total:
        return True
    return False, f"{ok}/{total} valid responses"


def test_slow_request_headers(addr: tuple[str, int]) -> bool | tuple[bool, str]:
    """Client that sends headers slowly still gets a response."""
    s = connect(addr)
    s.settimeout(10)
    try:
        s.sendall(b"GET / HTTP/1.1\r\n")
        time.sleep(0.5)
        s.sendall(b"Host: localhost\r\n")
        time.sleep(0.5)
        s.sendall(b"Connection: close\r\n\r\n")

        resp = recv_close_response(s)
        status = parse_status(resp)
        if is_valid(status):
            return True
        return False, f"Status: {status}"
    finally:
        s.close()


def test_slow_client_doesnt_starve(addr: tuple[str, int]) -> bool | tuple[bool, str]:
    """A slow client doesn't prevent other clients from being served."""
    # Open a connection that sends a partial request and stalls
    slow = connect(addr)
    slow.settimeout(10)
    slow.sendall(b"GET / HTTP/1.1\r\nHost: localhost\r\n")
    # Don't finish — leave it hanging

    time.sleep(0.5)

    # A normal request should still succeed
    fast = connect(addr)
    fast.settimeout(5)
    try:
        fast.sendall(CLOSE_GET)
        resp = recv_close_response(fast)
        status = parse_status(resp)
    finally:
        fast.close()
        slow.close()

    if is_valid(status):
        return True
    return False, f"Normal client got status {status} while slow client was stalled"


def test_thread_pool_exhaustion(
    addr: tuple[str, int], threads: int
) -> bool | tuple[bool, str]:
    """Slow clients saturating all threads don't block new requests.

    Opens enough connections to fill every thread pool slot with a slow
    client, then checks whether a normal request can still be served.
    Without thread pool exhaustion protection, the normal request times
    out because all threads are blocked reading from slow sockets.
    """
    slow_conns = []
    try:
        # Saturate the thread pool: each slow connection sends just enough
        # for the poller to see readable data and submit to the thread pool,
        # but not enough to complete the request (missing final \r\n).
        for _ in range(threads):
            s = connect(addr)
            s.settimeout(10)
            s.sendall(b"GET / HTTP/1.1\r\nHost: localhost\r\n")
            slow_conns.append(s)

        # Give the server time to pick up all slow connections into threads
        time.sleep(1)

        # Now try a normal request — all thread pool slots should be occupied
        fast = connect(addr)
        fast.settimeout(3)
        try:
            fast.sendall(CLOSE_GET)
            resp = recv_close_response(fast)
            status = parse_status(resp)
        except (TimeoutError, OSError):
            status = 0
        finally:
            fast.close()

        if is_valid(status):
            return True
        return (
            False,
            f"Normal request blocked (status={status}) "
            f"— all {threads} threads exhausted by slow clients",
        )
    finally:
        for s in slow_conns:
            s.close()


def test_keepalive_after_post_body(addr: tuple[str, int]) -> bool | tuple[bool, str]:
    """Keep-alive works after a POST with a 1KB body."""
    s = connect(addr)
    s.settimeout(10)
    try:
        body = b"x" * 1024
        post = (
            b"POST / HTTP/1.1\r\n"
            b"Host: localhost\r\n"
            b"Content-Length: " + str(len(body)).encode() + b"\r\n"
            b"\r\n" + body
        )
        s.sendall(post)
        resp1 = recv_response(s)
        status1 = parse_status(resp1)
        if not is_valid(status1):
            return False, f"POST response status: {status1}"

        s.sendall(SIMPLE_GET)
        resp2 = recv_response(s)
        status2 = parse_status(resp2)
        if is_valid(status2):
            return True
        return False, f"POST: {status1}, GET: {status2}"
    finally:
        s.close()


def test_keepalive_after_large_body(addr: tuple[str, int]) -> bool | tuple[bool, str]:
    """Keep-alive works after a POST with a 64KB body."""
    s = connect(addr)
    s.settimeout(10)
    try:
        body = b"x" * 65536
        post = (
            b"POST / HTTP/1.1\r\n"
            b"Host: localhost\r\n"
            b"Content-Length: " + str(len(body)).encode() + b"\r\n"
            b"\r\n" + body
        )
        s.sendall(post)
        resp1 = recv_response(s)
        status1 = parse_status(resp1)
        if not is_valid(status1):
            return False, f"POST response status: {status1}"

        s.sendall(SIMPLE_GET)
        resp2 = recv_response(s)
        status2 = parse_status(resp2)
        if is_valid(status2):
            return True
        return False, f"POST: {status1}, GET: {status2}"
    finally:
        s.close()


def test_keepalive_after_chunked_body(
    addr: tuple[str, int],
) -> bool | tuple[bool, str]:
    """Keep-alive works after a chunked POST body."""
    s = connect(addr)
    s.settimeout(10)
    try:
        chunk_data = b"Hello, chunked world!"
        chunk_size = f"{len(chunk_data):X}".encode()
        post = (
            b"POST / HTTP/1.1\r\n"
            b"Host: localhost\r\n"
            b"Transfer-Encoding: chunked\r\n"
            b"\r\n" + chunk_size + b"\r\n" + chunk_data + b"\r\n"
            b"0\r\n"
            b"\r\n"
        )
        s.sendall(post)
        resp1 = recv_response(s)
        status1 = parse_status(resp1)
        if not is_valid(status1):
            return False, f"Chunked POST response status: {status1}"

        s.sendall(SIMPLE_GET)
        resp2 = recv_response(s)
        status2 = parse_status(resp2)
        if is_valid(status2):
            return True
        return False, f"POST: {status1}, GET: {status2}"
    finally:
        s.close()


def test_large_body_bridge(addr: tuple[str, int]) -> bool | tuple[bool, str]:
    """Large POST body (3MB, above default 2.5MB limit) gets a response."""
    s = connect(addr)
    s.settimeout(30)
    try:
        body = b"x" * (3 * 1024 * 1024)  # 3MB
        post = (
            b"POST / HTTP/1.1\r\n"
            b"Host: localhost\r\n"
            b"Connection: close\r\n"
            b"Content-Length: " + str(len(body)).encode() + b"\r\n"
            b"\r\n" + body
        )
        s.sendall(post)
        resp = recv_close_response(s)
        status = parse_status(resp)
        if is_valid(status):
            return True
        return False, f"Status: {status}"
    finally:
        s.close()


def test_expect_100_continue(addr: tuple[str, int]) -> bool | tuple[bool, str]:
    """Server handles Expect: 100-continue correctly."""
    s = connect(addr)
    s.settimeout(10)
    try:
        body = b"test body content"
        post = (
            b"POST / HTTP/1.1\r\n"
            b"Host: localhost\r\n"
            b"Connection: close\r\n"
            b"Expect: 100-continue\r\n"
            b"Content-Length: " + str(len(body)).encode() + b"\r\n"
            b"\r\n"
        )
        s.sendall(post)

        # Wait for 100 Continue interim response
        buf = b""
        while b"\r\n\r\n" not in buf:
            chunk = s.recv(4096)
            if not chunk:
                return False, "Connection closed before 100 Continue"
            buf += chunk

        first_line = buf.split(b"\r\n")[0]
        if b"100" not in first_line:
            return False, f"Expected 100 Continue, got: {first_line!r}"

        # Now send the body
        s.sendall(body)

        # Read the final response (after the 100 Continue)
        resp = recv_close_response(s)

        # Find the final status — skip any leading data from the 100 response
        # that might still be in the buffer
        all_data = buf + resp
        # Look for the final HTTP status line (not the 100)
        final_status = 0
        for m in _STATUS_RE.finditer(all_data):
            code = int(m.group(1))
            if code != 100:
                final_status = code
                break

        if is_valid(final_status):
            return True
        return False, f"Final status: {final_status}"
    finally:
        s.close()


def test_keepalive_timeout(addr: tuple[str, int]) -> bool | tuple[bool, str]:
    """Server closes idle keep-alive connections after timeout (~2s)."""
    s = connect(addr)
    s.settimeout(10)
    try:
        s.sendall(SIMPLE_GET)
        resp = recv_response(s)
        status = parse_status(resp)
        if not is_valid(status):
            return False, f"Initial request status: {status}"

        # Wait longer than keepalive timeout (2s default + margin)
        time.sleep(3.5)

        try:
            data = s.recv(4096)
            if data == b"":
                return True  # Server closed
            return False, f"Expected EOF, got {len(data)} bytes"
        except (ConnectionResetError, BrokenPipeError):
            return True  # Server forcibly closed
        except TimeoutError:
            return False, "Connection still open after keepalive timeout"
    finally:
        s.close()


def test_healthcheck(addr: tuple[str, int]) -> bool | tuple[bool, str]:
    """Health check path returns 200 OK directly from the server layer."""
    s = connect(addr)
    s.settimeout(5)
    try:
        # The example app sets HEALTHCHECK_PATH = "/up/"
        req = b"GET /up/ HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n"
        s.sendall(req)
        resp = recv_close_response(s)
        status = parse_status(resp)
        if status != 200:
            return False, f"Expected 200, got {status}"
        if b"ok" not in resp:
            return False, f"Expected 'ok' body, got: {resp[-50:]!r}"
        return True
    finally:
        s.close()


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description="Server worker behavior tests")
    parser.add_argument("target", help="host:port of the server to test")
    parser.add_argument(
        "--threads",
        type=int,
        default=4,
        help="Thread count the server is running with (for exhaustion test)",
    )
    args = parser.parse_args()

    host, port_str = args.target.rsplit(":", 1)
    addr = (host, int(port_str))
    threads = args.threads

    tests: list[tuple[str, Callable[..., Any]]] = [
        ("Health check returns 200", test_healthcheck),
        ("Concurrent connections", test_concurrent_connections),
        ("Concurrent keep-alive sessions", test_concurrent_keepalive),
        ("Slow request headers", test_slow_request_headers),
        ("Slow client doesn't starve others", test_slow_client_doesnt_starve),
        (
            f"Thread pool exhaustion ({threads} threads)",
            lambda addr: test_thread_pool_exhaustion(addr, threads),
        ),
        ("Keep-alive after POST body (1KB)", test_keepalive_after_post_body),
        ("Keep-alive after POST body (64KB)", test_keepalive_after_large_body),
        ("Keep-alive after chunked POST body", test_keepalive_after_chunked_body),
        ("Large POST body (3MB, bridge path)", test_large_body_bridge),
        ("Expect: 100-continue", test_expect_100_continue),
        ("Keep-alive timeout closes connection", test_keepalive_timeout),
    ]

    print(f"\n{BOLD}Server Worker Behavior{RESET}\n")

    passed = 0
    failed = 0

    for i, (name, fn) in enumerate(tests, 1):
        try:
            result = fn(addr)
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
            print(f"  {GREEN}\u2713{RESET} {i}. {name}")
        else:
            failed += 1
            print(f"  {RED}\u2717{RESET} {i}. {name}")
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
