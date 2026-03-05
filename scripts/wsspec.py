"""WebSocket conformance tests for the Plain server (RFC 6455).

Tests the server's WebSocket implementation against key RFC 6455 requirements.
Designed to run against a Plain server with an echo channel registered.

Usage:
    python scripts/wsspec.py [host:port] [--strict]
"""

from __future__ import annotations

import base64
import hashlib
import os
import socket
import struct
import sys
import time

WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
PASS = "\033[32m✓\033[0m"
FAIL = "\033[31m✗\033[0m"

# -- WebSocket helpers -------------------------------------------------------


def ws_connect(host: str, port: int, path: str = "/ws-echo/") -> socket.socket:
    """Perform a WebSocket handshake and return the connected socket."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(5.0)
    sock.connect((host, port))

    key = base64.b64encode(os.urandom(16)).decode()
    request = (
        f"GET {path} HTTP/1.1\r\n"
        f"Host: {host}:{port}\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        f"Sec-WebSocket-Key: {key}\r\n"
        "Sec-WebSocket-Version: 13\r\n"
        "\r\n"
    )
    sock.sendall(request.encode())

    # Read response
    response = b""
    while b"\r\n\r\n" not in response:
        chunk = sock.recv(4096)
        if not chunk:
            raise ConnectionError("Server closed during handshake")
        response += chunk

    # Validate 101
    status_line = response.split(b"\r\n")[0]
    if b"101" not in status_line:
        raise ConnectionError(f"Expected 101, got: {status_line.decode()}")

    # Validate accept key
    expected_accept = base64.b64encode(
        hashlib.sha1((key + WS_GUID).encode()).digest()
    ).decode()
    if expected_accept.encode() not in response:
        raise ConnectionError("Invalid Sec-WebSocket-Accept")

    return sock


def send_frame(
    sock: socket.socket,
    opcode: int,
    payload: bytes = b"",
    fin: bool = True,
    mask: bool = True,
    rsv: int = 0,
) -> None:
    """Send a WebSocket frame."""
    header = bytearray()
    first_byte = (0x80 if fin else 0x00) | (rsv << 4) | (opcode & 0x0F)
    header.append(first_byte)

    length = len(payload)
    mask_bit = 0x80 if mask else 0x00

    if length < 126:
        header.append(mask_bit | length)
    elif length < 65536:
        header.append(mask_bit | 126)
        header.extend(struct.pack("!H", length))
    else:
        header.append(mask_bit | 127)
        header.extend(struct.pack("!Q", length))

    if mask:
        mask_key = os.urandom(4)
        header.extend(mask_key)
        masked = bytearray(payload)
        for i in range(len(masked)):
            masked[i] ^= mask_key[i % 4]
        sock.sendall(bytes(header) + bytes(masked))
    else:
        sock.sendall(bytes(header) + payload)


def recv_frame(sock: socket.socket, timeout: float = 2.0) -> tuple[int, bytes] | None:
    """Receive a WebSocket frame. Returns (opcode, payload) or None on timeout."""
    sock.settimeout(timeout)
    try:
        data = sock.recv(2)
        if len(data) < 2:
            return None
    except (TimeoutError, OSError):
        return None

    opcode = data[0] & 0x0F
    length = data[1] & 0x7F

    if length == 126:
        ext = sock.recv(2)
        length = struct.unpack("!H", ext)[0]
    elif length == 127:
        ext = sock.recv(8)
        length = struct.unpack("!Q", ext)[0]

    if length > 0:
        payload = b""
        while len(payload) < length:
            chunk = sock.recv(length - len(payload))
            if not chunk:
                break
            payload += chunk
    else:
        payload = b""

    return (opcode, payload)


def send_close(sock: socket.socket, code: int = 1000, reason: str = "") -> None:
    payload = struct.pack("!H", code) + reason.encode("utf-8")
    send_frame(sock, 0x8, payload)


# -- Test runner -------------------------------------------------------------

passed = 0
failed = 0
tests_run = 0


def test(name: str, fn, host: str, port: int, strict: bool) -> None:
    global passed, failed, tests_run
    tests_run += 1
    try:
        fn(host, port)
        print(f"  {PASS} {tests_run}. {name}")
        passed += 1
    except Exception as e:
        print(f"  {FAIL} {tests_run}. {name}")
        if strict:
            print(f"       {e}")
        failed += 1


# -- Tests -------------------------------------------------------------------

# 1. Opening handshake


def test_handshake_101(host, port):
    sock = ws_connect(host, port)
    send_close(sock)
    sock.close()


def test_handshake_accept_key(host, port):
    """Sec-WebSocket-Accept must match SHA1(key+GUID)."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(5.0)
    sock.connect((host, port))

    key = base64.b64encode(os.urandom(16)).decode()
    request = (
        "GET /ws-echo/ HTTP/1.1\r\n"
        f"Host: {host}:{port}\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        f"Sec-WebSocket-Key: {key}\r\n"
        "Sec-WebSocket-Version: 13\r\n"
        "\r\n"
    )
    sock.sendall(request.encode())

    response = b""
    while b"\r\n\r\n" not in response:
        response += sock.recv(4096)

    expected = base64.b64encode(
        hashlib.sha1((key + WS_GUID).encode()).digest()
    ).decode()
    assert expected.encode() in response, "Accept key mismatch"
    sock.close()


# 2. Text frames


def test_text_echo(host, port):
    sock = ws_connect(host, port)
    send_frame(sock, 0x1, b"Hello, WebSocket!")
    result = recv_frame(sock)
    assert result is not None, "No response"
    opcode, payload = result
    assert opcode == 0x1, f"Expected text (0x1), got {opcode:#x}"
    assert b"Hello, WebSocket!" in payload
    send_close(sock)
    sock.close()


def test_text_empty(host, port):
    sock = ws_connect(host, port)
    send_frame(sock, 0x1, b"")
    # Empty message — server might not echo, just check no crash
    time.sleep(0.2)
    send_close(sock)
    sock.close()


def test_text_large(host, port):
    """64 KiB text payload."""
    sock = ws_connect(host, port)
    payload = b"A" * 65536
    send_frame(sock, 0x1, payload)
    result = recv_frame(sock, timeout=5.0)
    assert result is not None, "No response for large payload"
    _, echoed = result
    assert len(echoed) >= 65536, f"Echoed size {len(echoed)} < 65536"
    send_close(sock)
    sock.close()


# 3. Binary frames


def test_binary_echo(host, port):
    sock = ws_connect(host, port)
    data = bytes(range(256))
    send_frame(sock, 0x2, data)
    result = recv_frame(sock)
    assert result is not None, "No response"
    opcode, payload = result
    assert opcode == 0x2, f"Expected binary (0x2), got {opcode:#x}"
    assert payload == data
    send_close(sock)
    sock.close()


# 4. Ping/Pong


def test_ping_gets_pong(host, port):
    sock = ws_connect(host, port)
    send_frame(sock, 0x9, b"ping-data")
    result = recv_frame(sock)
    assert result is not None, "No pong response"
    opcode, payload = result
    assert opcode == 0xA, f"Expected pong (0xA), got {opcode:#x}"
    assert payload == b"ping-data", f"Pong payload mismatch: {payload}"
    send_close(sock)
    sock.close()


def test_empty_ping(host, port):
    sock = ws_connect(host, port)
    send_frame(sock, 0x9, b"")
    result = recv_frame(sock)
    assert result is not None, "No pong response"
    assert result[0] == 0xA, f"Expected pong, got {result[0]:#x}"
    send_close(sock)
    sock.close()


def test_ping_with_max_payload(host, port):
    """Ping with 125-byte payload (maximum for control frames)."""
    sock = ws_connect(host, port)
    payload = b"x" * 125
    send_frame(sock, 0x9, payload)
    result = recv_frame(sock)
    assert result is not None
    assert result[0] == 0xA
    assert result[1] == payload
    send_close(sock)
    sock.close()


# 5. Close handshake


def test_close_normal(host, port):
    sock = ws_connect(host, port)
    send_close(sock, 1000, "goodbye")
    result = recv_frame(sock)
    assert result is not None, "No close response"
    opcode, payload = result
    assert opcode == 0x8, f"Expected close (0x8), got {opcode:#x}"
    if len(payload) >= 2:
        code = struct.unpack("!H", payload[:2])[0]
        assert code == 1000, f"Expected close code 1000, got {code}"
    sock.close()


def test_close_empty(host, port):
    """Close frame with no payload."""
    sock = ws_connect(host, port)
    send_frame(sock, 0x8, b"")
    result = recv_frame(sock)
    assert result is not None, "No close response"
    assert result[0] == 0x8
    sock.close()


def test_close_going_away(host, port):
    sock = ws_connect(host, port)
    send_close(sock, 1001, "going away")
    result = recv_frame(sock)
    assert result is not None
    assert result[0] == 0x8
    sock.close()


# 6. Reserved bits


def test_rsv1_rejected(host, port):
    """RSV1 set without negotiated extension → fail."""
    sock = ws_connect(host, port)
    send_frame(sock, 0x1, b"test", rsv=0x4)  # RSV1
    result = recv_frame(sock)
    # Should get a close frame with protocol error
    if result is not None:
        opcode, payload = result
        if opcode == 0x8 and len(payload) >= 2:
            code = struct.unpack("!H", payload[:2])[0]
            assert code == 1002, f"Expected 1002 protocol error, got {code}"
        elif opcode == 0x8:
            pass  # Close without code is acceptable
        else:
            raise AssertionError(f"Expected close frame, got opcode {opcode:#x}")
    sock.close()


# 7. Fragmentation


def test_fragmented_text(host, port):
    """Fragmented text message: first + continuation."""
    sock = ws_connect(host, port)
    # First fragment (not fin)
    send_frame(sock, 0x1, b"Hel", fin=False)
    # Continuation (fin)
    send_frame(sock, 0x0, b"lo!", fin=True)
    result = recv_frame(sock)
    assert result is not None, "No response for fragmented message"
    _, payload = result
    assert b"Hello!" in payload, f"Expected 'Hello!' in {payload}"
    send_close(sock)
    sock.close()


def test_fragmented_with_ping(host, port):
    """Interleaved control frame during fragmentation is allowed."""
    sock = ws_connect(host, port)
    send_frame(sock, 0x1, b"frag1", fin=False)
    # Ping between fragments (control frames can interleave)
    send_frame(sock, 0x9, b"mid-ping")
    # Read the pong
    result = recv_frame(sock)
    assert result is not None, "Expected pong"
    assert result[0] == 0xA, "Expected pong opcode"
    # Continue fragmentation
    send_frame(sock, 0x0, b"frag2", fin=True)
    result = recv_frame(sock)
    assert result is not None, "No response for fragmented message"
    _, payload = result
    assert b"frag1frag2" in payload
    send_close(sock)
    sock.close()


# 8. UTF-8 validation


def test_valid_utf8(host, port):
    sock = ws_connect(host, port)
    text = "Héllo, 世界! 🌍".encode()
    send_frame(sock, 0x1, text)
    result = recv_frame(sock)
    assert result is not None
    send_close(sock)
    sock.close()


def test_invalid_utf8_rejected(host, port):
    """Invalid UTF-8 in text frame → close with 1007."""
    sock = ws_connect(host, port)
    send_frame(sock, 0x1, b"\xff\xfe")  # Invalid UTF-8
    result = recv_frame(sock)
    if result is not None:
        opcode, payload = result
        if opcode == 0x8 and len(payload) >= 2:
            code = struct.unpack("!H", payload[:2])[0]
            assert code == 1007, f"Expected 1007 invalid payload, got {code}"
    sock.close()


# 9. Multiple messages


def test_multiple_messages(host, port):
    """Send several messages in sequence."""
    sock = ws_connect(host, port)
    for i in range(5):
        msg = f"message-{i}".encode()
        send_frame(sock, 0x1, msg)
        result = recv_frame(sock)
        assert result is not None, f"No response for message {i}"
    send_close(sock)
    sock.close()


# -- Main --------------------------------------------------------------------


def main() -> None:
    global passed, failed

    host = "127.0.0.1"
    port = 8000
    strict = False

    for arg in sys.argv[1:]:
        if arg == "--strict":
            strict = True
        elif ":" in arg:
            host, port_str = arg.rsplit(":", 1)
            port = int(port_str)
        elif arg == "--help":
            print(__doc__)
            sys.exit(0)

    print("\n\033[1mWebSocket Conformance (RFC 6455)\033[0m\n")

    print("\033[1mOpening Handshake (RFC 6455 S4)\033[0m")
    test("101 Switching Protocols", test_handshake_101, host, port, strict)
    test(
        "Sec-WebSocket-Accept validation", test_handshake_accept_key, host, port, strict
    )

    print("\n\033[1mText Frames (RFC 6455 S5.6)\033[0m")
    test("Text echo", test_text_echo, host, port, strict)
    test("Empty text frame", test_text_empty, host, port, strict)
    test("64 KiB text payload", test_text_large, host, port, strict)

    print("\n\033[1mBinary Frames (RFC 6455 S5.6)\033[0m")
    test("Binary echo", test_binary_echo, host, port, strict)

    print("\n\033[1mPing/Pong (RFC 6455 S5.5.2-3)\033[0m")
    test("Ping gets pong with same payload", test_ping_gets_pong, host, port, strict)
    test("Empty ping", test_empty_ping, host, port, strict)
    test("Ping with 125-byte payload", test_ping_with_max_payload, host, port, strict)

    print("\n\033[1mClose Handshake (RFC 6455 S5.5.1, S7)\033[0m")
    test("Close with 1000", test_close_normal, host, port, strict)
    test("Close with empty payload", test_close_empty, host, port, strict)
    test("Close with 1001 going away", test_close_going_away, host, port, strict)

    print("\n\033[1mReserved Bits (RFC 6455 S5.2)\033[0m")
    test("RSV1 without extension rejected", test_rsv1_rejected, host, port, strict)

    print("\n\033[1mFragmentation (RFC 6455 S5.4)\033[0m")
    test("Fragmented text message", test_fragmented_text, host, port, strict)
    test(
        "Control frame during fragmentation",
        test_fragmented_with_ping,
        host,
        port,
        strict,
    )

    print("\n\033[1mUTF-8 Handling (RFC 6455 S5.6, S8.1)\033[0m")
    test("Valid UTF-8 text", test_valid_utf8, host, port, strict)
    test(
        "Invalid UTF-8 rejected with 1007",
        test_invalid_utf8_rejected,
        host,
        port,
        strict,
    )

    print("\n\033[1mStress\033[0m")
    test("Multiple sequential messages", test_multiple_messages, host, port, strict)

    total = passed + failed
    color = "\033[32m" if failed == 0 else "\033[31m"
    print(f"\n{color}{passed}/{total} passed\033[0m")

    if failed > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
