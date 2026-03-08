"""WebSocket server worker behavior tests.

Tests handshake, echo (text/binary), concurrent connections, ping/pong,
close handshake, large messages, and abrupt disconnects at the socket
level. Run via ./tools/ws-worker-test or directly:

    python tools/ws-worker-test.py host:port

The server must have a WebSocket echo endpoint at /websocket/echo/.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import os
import socket
import struct
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
# WebSocket constants
# ---------------------------------------------------------------------------
WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
OP_TEXT = 0x1
OP_BINARY = 0x2
OP_CLOSE = 0x8
OP_PING = 0x9
OP_PONG = 0xA

# ---------------------------------------------------------------------------
# WebSocket client helpers
# ---------------------------------------------------------------------------


def ws_connect(addr: tuple[str, int], path: str = "/websocket/echo/") -> socket.socket:
    """Perform WebSocket opening handshake. Returns connected socket."""
    s = socket.create_connection(addr, timeout=10)
    s.settimeout(10)

    # Generate random key
    key = base64.b64encode(os.urandom(16)).decode()
    expected_accept = base64.b64encode(
        hashlib.sha1((key + WS_GUID).encode()).digest()
    ).decode()

    request = (
        f"GET {path} HTTP/1.1\r\n"
        f"Host: {addr[0]}:{addr[1]}\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        f"Sec-WebSocket-Key: {key}\r\n"
        "Sec-WebSocket-Version: 13\r\n"
        "\r\n"
    ).encode()
    s.sendall(request)

    # Read 101 response
    buf = b""
    while b"\r\n\r\n" not in buf:
        chunk = s.recv(4096)
        if not chunk:
            raise ConnectionError("Connection closed during handshake")
        buf += chunk

    status_line = buf.split(b"\r\n")[0]
    if b"101" not in status_line:
        raise ConnectionError(f"Handshake failed: {status_line.decode()}")

    # Verify Sec-WebSocket-Accept
    for line in buf.split(b"\r\n"):
        if line.lower().startswith(b"sec-websocket-accept:"):
            actual = line.split(b":", 1)[1].strip().decode()
            if actual != expected_accept:
                raise ConnectionError(
                    f"Bad Sec-WebSocket-Accept: {actual} != {expected_accept}"
                )
            break

    return s


def ws_send_frame(
    s: socket.socket,
    opcode: int,
    payload: bytes,
    fin: bool = True,
) -> None:
    """Send a masked WebSocket frame."""
    header = bytearray()
    first_byte = (0x80 if fin else 0x00) | (opcode & 0x0F)
    header.append(first_byte)

    mask_bit = 0x80
    length = len(payload)
    if length < 126:
        header.append(mask_bit | length)
    elif length < 65536:
        header.append(mask_bit | 126)
        header.extend(struct.pack("!H", length))
    else:
        header.append(mask_bit | 127)
        header.extend(struct.pack("!Q", length))

    mask = os.urandom(4)
    header.extend(mask)

    # Apply mask
    masked = bytearray(payload)
    for i in range(len(masked)):
        masked[i] ^= mask[i % 4]

    s.sendall(bytes(header) + bytes(masked))


def ws_send_text(s: socket.socket, text: str) -> None:
    """Send a text frame."""
    ws_send_frame(s, OP_TEXT, text.encode("utf-8"))


def ws_send_binary(s: socket.socket, data: bytes) -> None:
    """Send a binary frame."""
    ws_send_frame(s, OP_BINARY, data)


def ws_send_close(s: socket.socket, code: int = 1000, reason: str = "") -> None:
    """Send a close frame."""
    payload = struct.pack("!H", code) + reason.encode("utf-8")
    ws_send_frame(s, OP_CLOSE, payload)


def ws_send_ping(s: socket.socket, payload: bytes = b"") -> None:
    """Send a ping frame."""
    ws_send_frame(s, OP_PING, payload)


def ws_recv_frame(s: socket.socket) -> tuple[int, bytes]:
    """Read one WebSocket frame. Returns (opcode, payload).

    Server frames are unmasked.
    """
    data = _recv_exact(s, 2)
    first_byte, second_byte = data[0], data[1]
    opcode = first_byte & 0x0F
    masked = bool(second_byte & 0x80)
    length = second_byte & 0x7F

    if length == 126:
        length = struct.unpack("!H", _recv_exact(s, 2))[0]
    elif length == 127:
        length = struct.unpack("!Q", _recv_exact(s, 8))[0]

    if masked:
        mask = _recv_exact(s, 4)
    else:
        mask = None

    payload = _recv_exact(s, length) if length > 0 else b""

    if mask:
        payload = bytearray(payload)
        for i in range(len(payload)):
            payload[i] ^= mask[i % 4]
        payload = bytes(payload)

    return opcode, payload


def _recv_exact(s: socket.socket, n: int) -> bytes:
    """Read exactly n bytes from socket."""
    buf = b""
    while len(buf) < n:
        chunk = s.recv(n - len(buf))
        if not chunk:
            raise ConnectionError(f"Connection closed (needed {n}, got {len(buf)})")
        buf += chunk
    return buf


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_handshake(addr: tuple[str, int]) -> bool | tuple[bool, str]:
    """WebSocket handshake succeeds and returns 101."""
    s = ws_connect(addr)
    try:
        ws_send_close(s)
        return True
    finally:
        s.close()


def test_echo_text(addr: tuple[str, int]) -> bool | tuple[bool, str]:
    """Text message is echoed back."""
    s = ws_connect(addr)
    try:
        ws_send_text(s, "hello")
        opcode, payload = ws_recv_frame(s)
        if opcode == OP_TEXT and payload == b"hello":
            return True
        return False, f"opcode={opcode:#x}, payload={payload!r}"
    finally:
        ws_send_close(s)
        s.close()


def test_echo_binary(addr: tuple[str, int]) -> bool | tuple[bool, str]:
    """Binary message is echoed back."""
    s = ws_connect(addr)
    try:
        data = bytes(range(256))
        ws_send_binary(s, data)
        opcode, payload = ws_recv_frame(s)
        if opcode == OP_BINARY and payload == data:
            return True
        return False, f"opcode={opcode:#x}, len={len(payload)}"
    finally:
        ws_send_close(s)
        s.close()


def test_multiple_messages(addr: tuple[str, int]) -> bool | tuple[bool, str]:
    """Multiple messages on the same connection are all echoed."""
    s = ws_connect(addr)
    try:
        messages = [f"msg-{i}" for i in range(10)]
        for msg in messages:
            ws_send_text(s, msg)

        received = []
        for _ in range(10):
            opcode, payload = ws_recv_frame(s)
            if opcode != OP_TEXT:
                return (
                    False,
                    f"Unexpected opcode {opcode:#x} on message {len(received)}",
                )
            received.append(payload.decode("utf-8"))

        if received == messages:
            return True
        return False, f"Expected {messages}, got {received}"
    finally:
        ws_send_close(s)
        s.close()


def test_concurrent_connections(addr: tuple[str, int]) -> bool | tuple[bool, str]:
    """10 simultaneous WebSocket connections all work."""

    def do_echo(idx: int) -> bool:
        s = ws_connect(addr)
        try:
            msg = f"conn-{idx}"
            ws_send_text(s, msg)
            opcode, payload = ws_recv_frame(s)
            return opcode == OP_TEXT and payload.decode("utf-8") == msg
        finally:
            ws_send_close(s)
            s.close()

    n = 10
    with ThreadPoolExecutor(max_workers=n) as pool:
        futs = [pool.submit(do_echo, i) for i in range(n)]
        results = [f.result() for f in as_completed(futs)]

    ok = sum(1 for r in results if r)
    if ok == n:
        return True
    return False, f"{ok}/{n} connections succeeded"


def test_ping_pong(addr: tuple[str, int]) -> bool | tuple[bool, str]:
    """Server responds to ping with pong."""
    s = ws_connect(addr)
    try:
        ping_data = b"pingtest"
        ws_send_ping(s, ping_data)
        opcode, payload = ws_recv_frame(s)
        if opcode == OP_PONG and payload == ping_data:
            return True
        return False, f"opcode={opcode:#x}, payload={payload!r}"
    finally:
        ws_send_close(s)
        s.close()


def test_ping_empty(addr: tuple[str, int]) -> bool | tuple[bool, str]:
    """Server responds to empty ping with empty pong."""
    s = ws_connect(addr)
    try:
        ws_send_ping(s)
        opcode, payload = ws_recv_frame(s)
        if opcode == OP_PONG and payload == b"":
            return True
        return False, f"opcode={opcode:#x}, payload={payload!r}"
    finally:
        ws_send_close(s)
        s.close()


def test_close_handshake(addr: tuple[str, int]) -> bool | tuple[bool, str]:
    """Server responds to close frame with close frame."""
    s = ws_connect(addr)
    try:
        ws_send_close(s, 1000, "goodbye")
        opcode, payload = ws_recv_frame(s)
        if opcode != OP_CLOSE:
            return False, f"Expected close frame, got opcode={opcode:#x}"
        if len(payload) >= 2:
            code = struct.unpack("!H", payload[:2])[0]
            if code == 1000:
                return True
            return False, f"Close code: {code}"
        return True  # Empty close payload is also valid
    finally:
        s.close()


def test_close_no_reason(addr: tuple[str, int]) -> bool | tuple[bool, str]:
    """Close frame with just a code (no reason) works."""
    s = ws_connect(addr)
    try:
        ws_send_close(s, 1000)
        opcode, payload = ws_recv_frame(s)
        if opcode == OP_CLOSE:
            return True
        return False, f"Expected close, got opcode={opcode:#x}"
    finally:
        s.close()


def test_large_text_message(addr: tuple[str, int]) -> bool | tuple[bool, str]:
    """64KB text message is echoed correctly."""
    s = ws_connect(addr)
    try:
        # 64KB of ASCII text
        msg = "A" * 65536
        ws_send_text(s, msg)
        opcode, payload = ws_recv_frame(s)
        if opcode == OP_TEXT and len(payload) == 65536:
            return True
        return False, f"opcode={opcode:#x}, len={len(payload)}"
    finally:
        ws_send_close(s)
        s.close()


def test_large_binary_message(addr: tuple[str, int]) -> bool | tuple[bool, str]:
    """1MB binary message is echoed correctly."""
    s = ws_connect(addr)
    try:
        data = os.urandom(1024 * 1024)
        ws_send_binary(s, data)
        opcode, payload = ws_recv_frame(s)
        if opcode == OP_BINARY and payload == data:
            return True
        return False, f"opcode={opcode:#x}, len={len(payload)}"
    finally:
        ws_send_close(s)
        s.close()


def test_fragmented_text(addr: tuple[str, int]) -> bool | tuple[bool, str]:
    """Fragmented text message is reassembled and echoed."""
    s = ws_connect(addr)
    try:
        # Send "hello world" in 3 fragments
        ws_send_frame(s, OP_TEXT, b"hello", fin=False)
        ws_send_frame(s, 0x0, b" ", fin=False)  # continuation
        ws_send_frame(s, 0x0, b"world", fin=True)  # final continuation

        opcode, payload = ws_recv_frame(s)
        if opcode == OP_TEXT and payload == b"hello world":
            return True
        return False, f"opcode={opcode:#x}, payload={payload!r}"
    finally:
        ws_send_close(s)
        s.close()


def test_fragmented_binary(addr: tuple[str, int]) -> bool | tuple[bool, str]:
    """Fragmented binary message is reassembled and echoed."""
    s = ws_connect(addr)
    try:
        part1 = b"\x00\x01\x02\x03"
        part2 = b"\x04\x05\x06\x07"
        ws_send_frame(s, OP_BINARY, part1, fin=False)
        ws_send_frame(s, 0x0, part2, fin=True)

        opcode, payload = ws_recv_frame(s)
        if opcode == OP_BINARY and payload == part1 + part2:
            return True
        return False, f"opcode={opcode:#x}, payload={payload!r}"
    finally:
        ws_send_close(s)
        s.close()


def test_ping_between_fragments(addr: tuple[str, int]) -> bool | tuple[bool, str]:
    """Ping interleaved between fragments gets a pong, message reassembles."""
    s = ws_connect(addr)
    try:
        ws_send_frame(s, OP_TEXT, b"frag1", fin=False)
        ws_send_ping(s, b"mid-frag")
        ws_send_frame(s, 0x0, b"frag2", fin=True)

        # Should get pong first, then the reassembled echo
        frames = []
        for _ in range(2):
            opcode, payload = ws_recv_frame(s)
            frames.append((opcode, payload))

        pong_found = any(op == OP_PONG and pl == b"mid-frag" for op, pl in frames)
        echo_found = any(op == OP_TEXT and pl == b"frag1frag2" for op, pl in frames)

        if pong_found and echo_found:
            return True
        return False, f"frames: {[(hex(op), pl) for op, pl in frames]}"
    finally:
        ws_send_close(s)
        s.close()


def test_abrupt_disconnect(addr: tuple[str, int]) -> bool | tuple[bool, str]:
    """Server handles abrupt client disconnect without crashing.

    Opens a connection, sends a message, then closes the socket without
    a close handshake. Then verifies the server still accepts new connections.
    """
    s = ws_connect(addr)
    ws_send_text(s, "about to disconnect")
    ws_recv_frame(s)  # read the echo
    s.close()  # abrupt close, no close frame

    time.sleep(0.5)

    # Server should still work
    s2 = ws_connect(addr)
    try:
        ws_send_text(s2, "after disconnect")
        opcode, payload = ws_recv_frame(s2)
        if opcode == OP_TEXT and payload == b"after disconnect":
            return True
        return False, f"opcode={opcode:#x}, payload={payload!r}"
    finally:
        ws_send_close(s2)
        s2.close()


def test_invalid_handshake_no_upgrade(
    addr: tuple[str, int],
) -> bool | tuple[bool, str]:
    """Regular GET to WebSocket endpoint (no Upgrade header) gets non-101."""
    s = socket.create_connection(addr, timeout=5)
    s.settimeout(5)
    try:
        request = b"GET /websocket/echo/ HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n"
        s.sendall(request)
        buf = b""
        while b"\r\n\r\n" not in buf:
            chunk = s.recv(4096)
            if not chunk:
                break
            buf += chunk

        status_line = buf.split(b"\r\n")[0].decode()
        if "101" not in status_line:
            return True  # Good — not upgraded
        return False, f"Got 101 without Upgrade header: {status_line}"
    finally:
        s.close()


def test_data_after_echo(addr: tuple[str, int]) -> bool | tuple[bool, str]:
    """Rapid send/receive cycles work correctly."""
    s = ws_connect(addr)
    try:
        for i in range(50):
            msg = f"rapid-{i}"
            ws_send_text(s, msg)
            opcode, payload = ws_recv_frame(s)
            if opcode != OP_TEXT or payload.decode("utf-8") != msg:
                return (
                    False,
                    f"Mismatch at {i}: opcode={opcode:#x}, payload={payload!r}",
                )
        return True
    finally:
        ws_send_close(s)
        s.close()


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description="WebSocket worker behavior tests")
    parser.add_argument("target", help="host:port of the server to test")
    args = parser.parse_args()

    host, port_str = args.target.rsplit(":", 1)
    addr = (host, int(port_str))

    tests: list[tuple[str, Callable[..., Any]]] = [
        ("Handshake", test_handshake),
        ("Echo text", test_echo_text),
        ("Echo binary", test_echo_binary),
        ("Multiple messages on one connection", test_multiple_messages),
        ("Concurrent connections (10)", test_concurrent_connections),
        ("Ping/pong", test_ping_pong),
        ("Ping with empty payload", test_ping_empty),
        ("Close handshake", test_close_handshake),
        ("Close without reason", test_close_no_reason),
        ("Large text message (64KB)", test_large_text_message),
        ("Large binary message (1MB)", test_large_binary_message),
        ("Fragmented text message", test_fragmented_text),
        ("Fragmented binary message", test_fragmented_binary),
        ("Ping between fragments", test_ping_between_fragments),
        ("Abrupt client disconnect", test_abrupt_disconnect),
        ("Invalid handshake (no Upgrade)", test_invalid_handshake_no_upgrade),
        ("Rapid send/receive (50 cycles)", test_data_after_echo),
    ]

    print(f"\n{BOLD}WebSocket Worker Behavior{RESET}\n")

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
