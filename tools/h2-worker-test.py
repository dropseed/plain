"""HTTP/2 server worker behavior tests.

Tests concurrent streams, flow control, request bodies, stream resets,
and connection lifecycle over TLS+h2. Run via ./tools/h2-worker-test or:

    python tools/h2-worker-test.py host:port

The server must be running with TLS and ALPN h2 support.
"""

from __future__ import annotations

import argparse
import socket
import ssl
import sys
import time
from collections.abc import Callable
from typing import Any

import h2.config
import h2.connection
import h2.events
import h2.exceptions

# ---------------------------------------------------------------------------
# Colors
# ---------------------------------------------------------------------------
GREEN = "\033[32m"
RED = "\033[31m"
BOLD = "\033[1m"
DIM = "\033[2m"
RESET = "\033[0m"

# ---------------------------------------------------------------------------
# HTTP/2 client helpers
# ---------------------------------------------------------------------------


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
    method: str = "GET",
    path: str = "/",
    body: bytes | None = None,
) -> int:
    """Send a request with an optional small body. Returns stream ID."""
    stream_id = conn.get_next_available_stream_id()
    headers = [
        (":method", method),
        (":path", path),
        (":authority", "localhost"),
        (":scheme", "https"),
    ]

    if body is not None:
        headers.append(("content-length", str(len(body))))
        conn.send_headers(stream_id, headers)
        conn.send_data(stream_id, body, end_stream=True)
    else:
        conn.send_headers(stream_id, headers, end_stream=True)

    sock.sendall(conn.data_to_send())
    return stream_id


def _process_event(
    event: h2.events.Event,
    conn: h2.connection.H2Connection,
    responses: dict[int, dict[str, Any]],
) -> None:
    """Update responses dict from a single h2 event."""
    if isinstance(event, h2.events.ResponseReceived):
        sid = event.stream_id
        if sid in responses:
            responses[sid]["headers"] = event.headers
            for name, value in event.headers:
                if name == ":status":
                    responses[sid]["status"] = int(value)

    elif isinstance(event, h2.events.DataReceived):
        sid = event.stream_id
        if sid in responses:
            responses[sid]["data"] += event.data
        conn.acknowledge_received_data(event.flow_controlled_length, event.stream_id)

    elif isinstance(event, h2.events.StreamEnded):
        sid = event.stream_id
        if sid in responses:
            responses[sid]["ended"] = True

    elif isinstance(event, h2.events.StreamReset):
        sid = event.stream_id
        if sid in responses:
            responses[sid]["ended"] = True
            responses[sid]["reset_error_code"] = event.error_code


def collect_responses(
    conn: h2.connection.H2Connection,
    sock: ssl.SSLSocket,
    expected_streams: set[int],
    timeout: float = 10.0,
) -> dict[int, dict[str, Any]]:
    """Read from socket until all expected streams have completed."""
    responses: dict[int, dict[str, Any]] = {}
    for sid in expected_streams:
        responses[sid] = {
            "status": None,
            "headers": [],
            "data": b"",
            "ended": False,
            "reset_error_code": None,
        }

    deadline = time.monotonic() + timeout
    sock.settimeout(1.0)

    while time.monotonic() < deadline:
        if all(r["ended"] for r in responses.values()):
            break

        try:
            data = sock.recv(65535)
        except TimeoutError:
            continue
        if not data:
            break

        events = conn.receive_data(data)
        for event in events:
            _process_event(event, conn, responses)
        sock.sendall(conn.data_to_send())

    return responses


def send_large_body(
    conn: h2.connection.H2Connection,
    sock: ssl.SSLSocket,
    body: bytes,
    path: str = "/",
) -> tuple[int, dict[str, Any]]:
    """Send a POST with a large body, handling flow control interleaving.

    Returns (stream_id, response_dict). The server may respond (e.g. 413)
    before the entire body is sent.
    """
    stream_id = conn.get_next_available_stream_id()
    headers = [
        (":method", "POST"),
        (":path", path),
        (":authority", "localhost"),
        (":scheme", "https"),
        ("content-length", str(len(body))),
    ]
    conn.send_headers(stream_id, headers)
    sock.sendall(conn.data_to_send())

    response: dict[str, Any] = {
        "status": None,
        "headers": [],
        "data": b"",
        "ended": False,
        "reset_error_code": None,
    }
    responses = {stream_id: response}
    offset = 0
    deadline = time.monotonic() + 15.0
    sock.settimeout(1.0)

    while offset < len(body) and not response["ended"] and time.monotonic() < deadline:
        # Send ALL data the flow-control window allows (multiple frames)
        try:
            window = conn.local_flow_control_window(stream_id)
        except h2.exceptions.StreamClosedError:
            break

        send_failed = False
        while window > 0 and offset < len(body):
            chunk_size = min(window, conn.max_outbound_frame_size, len(body) - offset)
            is_last = offset + chunk_size >= len(body)
            try:
                conn.send_data(
                    stream_id, body[offset : offset + chunk_size], end_stream=is_last
                )
                offset += chunk_size
                window -= chunk_size
            except h2.exceptions.StreamClosedError:
                send_failed = True
                break

        try:
            sock.sendall(conn.data_to_send())
        except OSError:
            break

        if send_failed:
            break

        # Read from socket: use a short timeout if we just sent data (server
        # should respond quickly with WINDOW_UPDATE), block longer only when
        # the window is exhausted and we need a WINDOW_UPDATE to continue.
        try:
            remaining_window = conn.local_flow_control_window(stream_id)
        except h2.exceptions.StreamClosedError:
            break
        sock.settimeout(0.05 if remaining_window > 0 else 1.0)
        try:
            data = sock.recv(65535)
            if not data:
                break
            events = conn.receive_data(data)
            for event in events:
                _process_event(event, conn, responses)
            sock.sendall(conn.data_to_send())
        except TimeoutError:
            pass

    # If body fully sent but no response yet, wait for it
    if not response["ended"]:
        remaining = collect_responses(conn, sock, {stream_id}, timeout=5.0)
        r = remaining[stream_id]
        if r["status"] is not None:
            response["status"] = r["status"]
        response["data"] += r["data"]
        response["ended"] = r["ended"]
        if r.get("reset_error_code") is not None:
            response["reset_error_code"] = r["reset_error_code"]

    return stream_id, response


def drain_socket(
    conn: h2.connection.H2Connection,
    sock: ssl.SSLSocket,
    duration: float = 0.5,
) -> None:
    """Read and discard data from the socket for a short period."""
    sock.settimeout(0.2)
    deadline = time.monotonic() + duration
    while time.monotonic() < deadline:
        try:
            data = sock.recv(65535)
            if not data:
                break
            conn.receive_data(data)
            sock.sendall(conn.data_to_send())
        except TimeoutError:
            pass


def is_valid(status: int | None) -> bool:
    return status is not None and 100 <= status <= 599


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_single_request(addr: tuple[str, int]) -> bool | tuple[bool, str]:
    """Basic HTTP/2 request gets a valid response."""
    sock, conn = create_h2_connection(addr)
    try:
        sid = send_request(conn, sock)
        responses = collect_responses(conn, sock, {sid})
        status = responses[sid]["status"]
        if is_valid(status):
            return True
        return False, f"Status: {status}"
    finally:
        sock.close()


def test_concurrent_streams(addr: tuple[str, int]) -> bool | tuple[bool, str]:
    """10 concurrent streams on a single connection all complete."""
    sock, conn = create_h2_connection(addr)
    try:
        n = 10
        stream_ids = set()
        for _ in range(n):
            sid = send_request(conn, sock)
            stream_ids.add(sid)

        responses = collect_responses(conn, sock, stream_ids)
        ok = sum(1 for r in responses.values() if is_valid(r["status"]))
        if ok == n:
            return True
        statuses = {sid: r["status"] for sid, r in responses.items()}
        return False, f"{ok}/{n} valid responses: {statuses}"
    finally:
        sock.close()


def test_sequential_streams(addr: tuple[str, int]) -> bool | tuple[bool, str]:
    """5 sequential requests on the same connection reuse it properly."""
    sock, conn = create_h2_connection(addr)
    try:
        for i in range(5):
            sid = send_request(conn, sock)
            responses = collect_responses(conn, sock, {sid})
            status = responses[sid]["status"]
            if not is_valid(status):
                return False, f"Request {i + 1} got status {status}"
        return True
    finally:
        sock.close()


def test_post_with_body(addr: tuple[str, int]) -> bool | tuple[bool, str]:
    """POST with a 1KB body gets a valid response."""
    sock, conn = create_h2_connection(addr)
    try:
        body = b"x" * 1024
        sid = send_request(conn, sock, method="POST", path="/", body=body)
        responses = collect_responses(conn, sock, {sid})
        status = responses[sid]["status"]
        if is_valid(status):
            return True
        return False, f"Status: {status}"
    finally:
        sock.close()


def test_oversized_body_413(addr: tuple[str, int]) -> bool | tuple[bool, str]:
    """POST body exceeding DATA_UPLOAD_MAX_MEMORY_SIZE gets 413."""
    sock, conn = create_h2_connection(addr)
    try:
        # Default DATA_UPLOAD_MAX_MEMORY_SIZE is 2621440 (2.5 MB)
        body = b"x" * (3 * 1024 * 1024)
        _, response = send_large_body(conn, sock, body)
        status = response["status"]
        if status == 413:
            return True
        return (
            False,
            f"Expected 413, got status={status}, reset_error_code={response.get('reset_error_code')}",
        )
    finally:
        sock.close()


def test_connection_reuse_after_413(
    addr: tuple[str, int],
) -> bool | tuple[bool, str]:
    """Connection still works for new requests after a 413 rejection."""
    sock, conn = create_h2_connection(addr)
    try:
        # Trigger a 413
        body = b"x" * (3 * 1024 * 1024)
        _, response = send_large_body(conn, sock, body)
        if response["status"] != 413:
            return (
                False,
                f"Setup failed: expected 413, got {response['status']}",
            )

        # Drain any leftover frames from the 413 exchange
        drain_socket(conn, sock, duration=0.5)

        # A fresh request on the same connection should succeed
        sid = send_request(conn, sock)
        responses = collect_responses(conn, sock, {sid})
        status = responses[sid]["status"]
        if is_valid(status):
            return True
        return False, f"Post-413 request got status {status}"
    finally:
        sock.close()


def test_connection_after_stream_reset(
    addr: tuple[str, int],
) -> bool | tuple[bool, str]:
    """Connection still works after client resets a stream."""
    sock, conn = create_h2_connection(addr)
    try:
        # Send a request then immediately reset it
        sid1 = send_request(conn, sock)
        conn.reset_stream(sid1)
        sock.sendall(conn.data_to_send())

        # Drain pending data from the reset stream
        drain_socket(conn, sock, duration=0.5)

        # Now send a normal request — should work fine
        sid2 = send_request(conn, sock)
        responses = collect_responses(conn, sock, {sid2})
        status = responses[sid2]["status"]
        if is_valid(status):
            return True
        return False, f"Post-reset request got status {status}"
    finally:
        sock.close()


def test_response_body_received(addr: tuple[str, int]) -> bool | tuple[bool, str]:
    """Response body is received completely with flow control."""
    sock, conn = create_h2_connection(addr)
    try:
        sid = send_request(conn, sock)
        responses = collect_responses(conn, sock, {sid})
        status = responses[sid]["status"]
        body = responses[sid]["data"]
        if is_valid(status) and len(body) > 0:
            return True
        return False, f"Status: {status}, body length: {len(body)}"
    finally:
        sock.close()


def test_concurrent_posts(addr: tuple[str, int]) -> bool | tuple[bool, str]:
    """5 concurrent POST streams with bodies all complete."""
    sock, conn = create_h2_connection(addr)
    try:
        n = 5
        stream_ids = set()
        for i in range(n):
            body = f"request-{i}-".encode() * 100
            sid = send_request(conn, sock, method="POST", path="/", body=body)
            stream_ids.add(sid)

        responses = collect_responses(conn, sock, stream_ids)
        ok = sum(1 for r in responses.values() if is_valid(r["status"]))
        if ok == n:
            return True
        statuses = {sid: r["status"] for sid, r in responses.items()}
        return False, f"{ok}/{n} valid responses: {statuses}"
    finally:
        sock.close()


def test_rst_mid_response(addr: tuple[str, int]) -> bool | tuple[bool, str]:
    """RST_STREAM mid-response doesn't break another stream."""
    sock, conn = create_h2_connection(addr)
    try:
        # Send two requests
        sid1 = send_request(conn, sock)
        sid2 = send_request(conn, sock)

        # Wait briefly for the server to start responding
        sock.settimeout(1.0)
        try:
            data = sock.recv(65535)
            if data:
                conn.receive_data(data)
                sock.sendall(conn.data_to_send())
        except TimeoutError:
            pass

        # Reset the first stream
        try:
            conn.reset_stream(sid1)
            sock.sendall(conn.data_to_send())
        except h2.exceptions.StreamClosedError:
            pass  # Already finished — that's fine

        # The second stream should still complete
        responses = collect_responses(conn, sock, {sid2})
        status = responses[sid2]["status"]
        if is_valid(status):
            return True
        return False, f"Second stream got status {status}"
    finally:
        sock.close()


def test_multiple_connections(addr: tuple[str, int]) -> bool | tuple[bool, str]:
    """Multiple independent HTTP/2 connections work simultaneously."""
    connections = []
    try:
        n = 5
        stream_map: list[tuple[ssl.SSLSocket, h2.connection.H2Connection, int]] = []
        for _ in range(n):
            sock, conn = create_h2_connection(addr)
            connections.append((sock, conn))
            sid = send_request(conn, sock)
            stream_map.append((sock, conn, sid))

        ok = 0
        for sock, conn, sid in stream_map:
            responses = collect_responses(conn, sock, {sid})
            if is_valid(responses[sid]["status"]):
                ok += 1

        if ok == n:
            return True
        return False, f"{ok}/{n} connections got valid responses"
    finally:
        for sock, _ in connections:
            sock.close()


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description="HTTP/2 server worker behavior tests")
    parser.add_argument("target", help="host:port of the TLS server to test")
    args = parser.parse_args()

    host, port_str = args.target.rsplit(":", 1)
    addr = (host, int(port_str))

    tests: list[tuple[str, Callable[..., Any]]] = [
        ("Single request", test_single_request),
        ("Concurrent streams (10)", test_concurrent_streams),
        ("Sequential streams on same connection", test_sequential_streams),
        ("POST with request body (1KB)", test_post_with_body),
        ("Oversized body gets 413", test_oversized_body_413),
        ("Connection reuse after 413", test_connection_reuse_after_413),
        ("Connection survives stream reset", test_connection_after_stream_reset),
        ("Response body with flow control", test_response_body_received),
        ("Concurrent POST streams with bodies", test_concurrent_posts),
        ("RST_STREAM mid-response", test_rst_mid_response),
        ("Multiple independent connections", test_multiple_connections),
    ]

    print(f"\n{BOLD}HTTP/2 Worker Behavior{RESET}\n")

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
