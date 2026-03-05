"""Tests for the plain.channels infrastructure.

Tests are organized in three levels:
1. Unit tests — SSE formatting, WebSocket framing, channel registry (no infrastructure needed)
2. Integration tests — SSE/WebSocket connections with socket pairs (no Postgres)
3. Postgres integration — PostgresListener + full pipeline (needs DATABASE_URL)
"""

import asyncio
import os
import socket
import struct

import pytest

from plain.channels.channel import Channel
from plain.channels.registry import ChannelRegistry
from plain.channels.sse import SSE_HEADERS, format_sse_comment, format_sse_event
from plain.channels.websocket import (
    CLOSE_NORMAL,
    CLOSE_PROTOCOL_ERROR,
    OP_BINARY,
    OP_CLOSE,
    OP_PING,
    OP_PONG,
    OP_TEXT,
    _apply_mask,
    build_accept_response,
    compute_accept_key,
    encode_close,
    encode_frame,
    parse_close_payload,
    read_frame,
    validate_handshake_headers,
)


# ---------------------------------------------------------------------------
# Test channel for use in integration tests
# ---------------------------------------------------------------------------
class StubChannel(Channel):
    path = "/test-events/"

    def authorize(self, request):
        return True

    def subscribe(self, request):
        return ["test_chan"]


class EchoChannel(Channel):
    """WebSocket echo channel for testing."""

    path = "/ws-echo/"

    def authorize(self, request):
        return True

    def subscribe(self, request):
        return ["echo_chan"]

    def receive(self, message):
        return message

    def transform(self, channel_name, payload):
        return payload


# ===================================================================
# Level 1: Unit tests (no infrastructure)
# ===================================================================


class TestSSEFormatting:
    def test_format_event_simple(self):
        result = format_sse_event("hello")
        assert result == b"data: hello\n\n"

    def test_format_event_with_type(self):
        result = format_sse_event("hello", event="message")
        assert b"event: message\n" in result
        assert b"data: hello\n" in result

    def test_format_event_with_id(self):
        result = format_sse_event("hello", event_id="42")
        assert b"id: 42\n" in result

    def test_format_event_with_retry(self):
        result = format_sse_event("hello", retry=3000)
        assert b"retry: 3000\n" in result

    def test_format_event_dict_payload(self):
        result = format_sse_event({"key": "value"})
        assert b'data: {"key": "value"}\n\n' == result

    def test_format_event_multiline(self):
        result = format_sse_event("line1\nline2")
        assert b"data: line1\ndata: line2\n\n" == result

    def test_format_event_none_payload(self):
        result = format_sse_event(None)
        assert b"data: \n\n" == result

    def test_format_comment(self):
        result = format_sse_comment("heartbeat")
        assert result == b": heartbeat\n\n"

    def test_format_comment_empty(self):
        result = format_sse_comment()
        assert result == b": \n\n"

    def test_sse_headers(self):
        header_dict = dict(SSE_HEADERS)
        assert header_dict["Content-Type"] == "text/event-stream"
        assert header_dict["Cache-Control"] == "no-cache"
        assert header_dict["Connection"] == "keep-alive"


class TestChannelRegistry:
    def test_register_and_match(self):
        registry = ChannelRegistry()

        @registry.register
        class MyChannel(Channel):
            path = "/events/"

        assert registry.match("/events/") is not None
        assert registry.match("/events/").path == "/events/"

    def test_match_returns_none_for_unknown(self):
        registry = ChannelRegistry()
        assert registry.match("/unknown/") is None

    def test_register_requires_path(self):
        registry = ChannelRegistry()
        with pytest.raises(ValueError, match="must define a 'path'"):

            @registry.register
            class BadChannel(Channel):
                pass

    def test_get_all(self):
        registry = ChannelRegistry()

        @registry.register
        class Chan1(Channel):
            path = "/a/"

        @registry.register
        class Chan2(Channel):
            path = "/b/"

        all_channels = registry.get_all()
        assert len(all_channels) == 2
        assert "/a/" in all_channels
        assert "/b/" in all_channels


class TestChannelBaseClass:
    def test_default_authorize(self):
        ch = Channel()
        assert ch.authorize(None) is True

    def test_default_subscribe(self):
        ch = Channel()
        assert ch.subscribe(None) == []

    def test_default_transform(self):
        ch = Channel()
        assert ch.transform("chan", "payload") == "payload"

    def test_default_receive(self):
        ch = Channel()
        assert ch.receive("hello") is None

    def test_echo_channel_receive(self):
        ch = EchoChannel()
        assert ch.receive("hello") == "hello"


class TestWebSocketFrameProtocol:
    """Unit tests for WebSocket frame encoding/decoding."""

    def test_encode_text_frame(self):
        frame = encode_frame(OP_TEXT, b"hello")
        assert frame[0] == 0x81  # FIN + TEXT
        assert frame[1] == 5  # payload length
        assert frame[2:] == b"hello"

    def test_encode_binary_frame(self):
        frame = encode_frame(OP_BINARY, b"\x00\x01\x02")
        assert frame[0] == 0x82  # FIN + BINARY
        assert frame[1] == 3

    def test_encode_empty_frame(self):
        frame = encode_frame(OP_TEXT, b"")
        assert frame[0] == 0x81
        assert frame[1] == 0

    def test_encode_medium_payload(self):
        """Payload 126-65535 bytes uses 2-byte extended length."""
        payload = b"x" * 200
        frame = encode_frame(OP_TEXT, payload)
        assert frame[1] == 126
        length = struct.unpack("!H", frame[2:4])[0]
        assert length == 200
        assert frame[4:] == payload

    def test_encode_large_payload(self):
        """Payload > 65535 bytes uses 8-byte extended length."""
        payload = b"x" * 70000
        frame = encode_frame(OP_TEXT, payload)
        assert frame[1] == 127
        length = struct.unpack("!Q", frame[2:10])[0]
        assert length == 70000

    def test_encode_no_fin(self):
        frame = encode_frame(OP_TEXT, b"partial", fin=False)
        assert frame[0] == 0x01  # no FIN + TEXT

    def test_encode_ping(self):
        frame = encode_frame(OP_PING, b"")
        assert frame[0] == 0x89  # FIN + PING
        assert frame[1] == 0

    def test_encode_pong(self):
        frame = encode_frame(OP_PONG, b"data")
        assert frame[0] == 0x8A  # FIN + PONG

    def test_encode_close(self):
        frame = encode_close(CLOSE_NORMAL, "bye")
        assert frame[0] == 0x88  # FIN + CLOSE
        # Payload: 2-byte code + reason
        payload = frame[2:]
        code = struct.unpack("!H", payload[:2])[0]
        assert code == 1000
        assert payload[2:] == b"bye"

    def test_apply_mask(self):
        mask = b"\x37\xfa\x21\x3d"
        data = b"Hello"
        masked = _apply_mask(data, mask)
        # Unmasking is the same operation
        assert _apply_mask(masked, mask) == data

    def test_parse_close_payload_normal(self):
        payload = struct.pack("!H", 1000) + b"goodbye"
        result = parse_close_payload(payload)
        assert result.code == 1000
        assert result.reason == "goodbye"

    def test_parse_close_payload_empty(self):
        result = parse_close_payload(b"")
        assert result.code == 1005  # CLOSE_NO_STATUS

    def test_parse_close_payload_single_byte(self):
        result = parse_close_payload(b"\x00")
        assert result.code == CLOSE_PROTOCOL_ERROR

    def test_compute_accept_key(self):
        key = "dGhlIHNhbXBsZSBub25jZQ=="
        expected = "cOfHahk5/XGjY8XhRkGxODLWrNc="
        assert compute_accept_key(key) == expected


class TestWebSocketHandshakeValidation:
    """Unit tests for WebSocket upgrade request validation."""

    def test_valid_upgrade(self):
        headers = [
            ("CONNECTION", "Upgrade"),
            ("UPGRADE", "websocket"),
            ("SEC-WEBSOCKET-KEY", "dGhlIHNhbXBsZSBub25jZQ=="),
            ("SEC-WEBSOCKET-VERSION", "13"),
        ]
        is_ws, key, error = validate_handshake_headers(headers)
        assert is_ws is True
        assert key == "dGhlIHNhbXBsZSBub25jZQ=="
        assert error == ""

    def test_not_websocket(self):
        headers = [("CONNECTION", "keep-alive")]
        is_ws, key, error = validate_handshake_headers(headers)
        assert is_ws is False

    def test_wrong_version(self):
        headers = [
            ("CONNECTION", "Upgrade"),
            ("UPGRADE", "websocket"),
            ("SEC-WEBSOCKET-KEY", "dGhlIHNhbXBsZSBub25jZQ=="),
            ("SEC-WEBSOCKET-VERSION", "8"),
        ]
        is_ws, _, error = validate_handshake_headers(headers)
        assert is_ws is True
        assert "version" in error.lower()

    def test_missing_key(self):
        headers = [
            ("CONNECTION", "Upgrade"),
            ("UPGRADE", "websocket"),
            ("SEC-WEBSOCKET-VERSION", "13"),
        ]
        is_ws, _, error = validate_handshake_headers(headers)
        assert is_ws is True
        assert "Key" in error

    def test_build_accept_response(self):
        resp = build_accept_response("dGhlIHNhbXBsZSBub25jZQ==")
        assert b"HTTP/1.1 101 Switching Protocols" in resp
        assert b"Upgrade: websocket" in resp
        assert b"Connection: Upgrade" in resp
        assert b"cOfHahk5/XGjY8XhRkGxODLWrNc=" in resp


class TestReadFrame:
    """Unit tests for async frame reading."""

    def _make_masked_frame(self, opcode, payload, fin=True, mask=b"\x01\x02\x03\x04"):
        """Build a client→server masked frame."""
        header = bytearray()
        first_byte = (0x80 if fin else 0x00) | (opcode & 0x0F)
        header.append(first_byte)

        length = len(payload)
        if length < 126:
            header.append(0x80 | length)  # mask bit set
        elif length < 65536:
            header.append(0x80 | 126)
            header.extend(struct.pack("!H", length))
        else:
            header.append(0x80 | 127)
            header.extend(struct.pack("!Q", length))

        header.extend(mask)
        masked_payload = _apply_mask(payload, mask)
        return bytes(header) + masked_payload

    def test_read_text_frame(self):
        data = self._make_masked_frame(OP_TEXT, b"hello")
        loop = asyncio.new_event_loop()
        try:
            reader = asyncio.StreamReader(loop=loop)
            reader.feed_data(data)

            async def run():
                return await read_frame(reader)

            frame = loop.run_until_complete(run())
            assert frame.fin is True
            assert frame.opcode == OP_TEXT
            assert frame.payload == b"hello"
        finally:
            loop.close()

    def test_read_binary_frame(self):
        data = self._make_masked_frame(OP_BINARY, b"\x00\x01\x02")
        loop = asyncio.new_event_loop()
        try:
            reader = asyncio.StreamReader(loop=loop)
            reader.feed_data(data)

            async def run():
                return await read_frame(reader)

            frame = loop.run_until_complete(run())
            assert frame.opcode == OP_BINARY
            assert frame.payload == b"\x00\x01\x02"
        finally:
            loop.close()

    def test_read_ping_frame(self):
        data = self._make_masked_frame(OP_PING, b"")
        loop = asyncio.new_event_loop()
        try:
            reader = asyncio.StreamReader(loop=loop)
            reader.feed_data(data)

            async def run():
                return await read_frame(reader)

            frame = loop.run_until_complete(run())
            assert frame.opcode == OP_PING
        finally:
            loop.close()

    def test_read_close_frame(self):
        close_payload = struct.pack("!H", 1000) + b"bye"
        data = self._make_masked_frame(OP_CLOSE, close_payload)
        loop = asyncio.new_event_loop()
        try:
            reader = asyncio.StreamReader(loop=loop)
            reader.feed_data(data)

            async def run():
                return await read_frame(reader)

            frame = loop.run_until_complete(run())
            assert frame.opcode == OP_CLOSE
            close = parse_close_payload(frame.payload)
            assert close.code == 1000
            assert close.reason == "bye"
        finally:
            loop.close()

    def test_reject_unmasked_frame(self):
        """Client frames must be masked."""
        # Build an unmasked frame manually
        data = bytes([0x81, 0x05]) + b"hello"  # no mask bit
        loop = asyncio.new_event_loop()
        try:
            reader = asyncio.StreamReader(loop=loop)
            reader.feed_data(data)

            async def run():
                return await read_frame(reader)

            with pytest.raises(ValueError, match="not masked"):
                loop.run_until_complete(run())
        finally:
            loop.close()

    def test_reject_rsv_bits(self):
        """RSV bits must be 0 (no extensions)."""
        # Set RSV1 bit
        header = bytearray(
            [0xC1, 0x80, 0x01, 0x02, 0x03, 0x04]
        )  # FIN+RSV1+TEXT, masked, 0 length
        loop = asyncio.new_event_loop()
        try:
            reader = asyncio.StreamReader(loop=loop)
            reader.feed_data(bytes(header))

            async def run():
                return await read_frame(reader)

            with pytest.raises(ValueError, match="RSV"):
                loop.run_until_complete(run())
        finally:
            loop.close()

    def test_fragmented_text(self):
        """Test reading fragmented message (first + continuation)."""
        frame1 = self._make_masked_frame(OP_TEXT, b"hel", fin=False)
        frame2 = self._make_masked_frame(0x0, b"lo", fin=True)  # continuation
        loop = asyncio.new_event_loop()
        try:
            reader = asyncio.StreamReader(loop=loop)
            reader.feed_data(frame1 + frame2)

            async def run():
                f1 = await read_frame(reader)
                f2 = await read_frame(reader)
                return f1, f2

            f1, f2 = loop.run_until_complete(run())
            assert f1.fin is False
            assert f1.opcode == OP_TEXT
            assert f1.payload == b"hel"
            assert f2.fin is True
            assert f2.opcode == 0x0  # continuation
            assert f2.payload == b"lo"
        finally:
            loop.close()


# ===================================================================
# Level 2: Integration tests — async pipeline with socket pairs
# ===================================================================


def _make_socket_pair():
    """Create a connected socket pair and return (server_fd_for_async, client_sock_for_reading).

    The returned fd is dup'd — the caller (SSEConnection) takes ownership.
    The client_sock should be used to read what the async side sends.
    """
    server_sock, client_sock = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
    dup_fd = os.dup(server_sock.fileno())
    server_sock.close()  # Close the original; async side owns the dup
    client_sock.setblocking(False)
    return dup_fd, client_sock


class TestSSEConnection:
    def test_open_sends_headers(self):
        """SSEConnection.open() should send HTTP 200 + SSE headers."""
        from plain.channels.handler import SSEConnection

        loop = asyncio.new_event_loop()
        fd, client = _make_socket_pair()
        try:
            conn = SSEConnection(fd, StubChannel(), ["test_chan"], loop)
            conn.open()

            # Read what was sent
            client.setblocking(True)
            client.settimeout(1.0)
            data = client.recv(4096)

            assert b"HTTP/1.1 200 OK" in data
            assert b"text/event-stream" in data
            assert b"Cache-Control: no-cache" in data

            conn.close()
        finally:
            client.close()
            loop.close()

    def test_send_event(self):
        """SSEConnection.send_event() should send formatted SSE data."""
        from plain.channels.handler import SSEConnection

        loop = asyncio.new_event_loop()
        fd, client = _make_socket_pair()
        try:
            conn = SSEConnection(fd, StubChannel(), ["test_chan"], loop)
            conn.open()

            # Drain the headers
            client.setblocking(True)
            client.settimeout(1.0)
            client.recv(4096)

            # Send an event
            result = loop.run_until_complete(conn.send_event("hello", event="msg"))
            assert result is True

            data = client.recv(4096)
            assert b"event: msg\n" in data
            assert b"data: hello\n" in data

            conn.close()
        finally:
            client.close()
            loop.close()

    def test_send_heartbeat(self):
        """SSEConnection.send_heartbeat() should send an SSE comment."""
        from plain.channels.handler import SSEConnection

        loop = asyncio.new_event_loop()
        fd, client = _make_socket_pair()
        try:
            conn = SSEConnection(fd, StubChannel(), ["test_chan"], loop)
            conn.open()

            client.setblocking(True)
            client.settimeout(1.0)
            client.recv(4096)  # drain headers

            result = loop.run_until_complete(conn.send_heartbeat())
            assert result is True

            data = client.recv(4096)
            assert b": heartbeat\n\n" in data

            conn.close()
        finally:
            client.close()
            loop.close()

    def test_send_to_closed_returns_false(self):
        """Sending to a closed connection should return False."""
        from plain.channels.handler import SSEConnection

        loop = asyncio.new_event_loop()
        fd, client = _make_socket_pair()
        try:
            conn = SSEConnection(fd, StubChannel(), ["test_chan"], loop)
            conn.open()
            conn.close()

            result = loop.run_until_complete(conn.send_event("hello"))
            assert result is False

            result = loop.run_until_complete(conn.send_heartbeat())
            assert result is False
        finally:
            client.close()
            loop.close()

    def test_send_to_broken_pipe_returns_false(self):
        """Sending after the client disconnects should return False."""
        from plain.channels.handler import SSEConnection

        loop = asyncio.new_event_loop()
        fd, client = _make_socket_pair()
        try:
            conn = SSEConnection(fd, StubChannel(), ["test_chan"], loop)
            conn.open()

            client.setblocking(True)
            client.settimeout(1.0)
            client.recv(4096)  # drain headers

            # Close the client end to simulate disconnect
            client.close()

            result = loop.run_until_complete(conn.send_event("hello"))
            assert result is False
        finally:
            loop.close()


class TestAsyncConnectionManager:
    def test_accept_and_dispatch(self):
        """Accept a connection then dispatch an event — data should arrive."""
        from plain.channels.handler import AsyncConnectionManager

        loop = asyncio.new_event_loop()
        fd, client = _make_socket_pair()
        try:
            manager = AsyncConnectionManager(loop)

            async def run():
                # Accept
                await manager._accept_sse_async(fd, StubChannel(), ["test_chan"])
                assert len(manager._connections) == 1

                # Dispatch
                await manager.dispatch_event("test_chan", "payload123")

            loop.run_until_complete(run())

            # Read from client
            client.setblocking(True)
            client.settimeout(1.0)
            data = client.recv(8192)

            # Should contain headers + event
            assert b"HTTP/1.1 200 OK" in data
            assert b"data: payload123" in data
            assert b"event: test_chan" in data

            manager.close_all()
        finally:
            client.close()
            loop.close()

    def test_dispatch_to_wrong_channel_is_silent(self):
        """Dispatching to a channel no one subscribes to should be a no-op."""
        from plain.channels.handler import AsyncConnectionManager

        loop = asyncio.new_event_loop()
        fd, client = _make_socket_pair()
        try:
            manager = AsyncConnectionManager(loop)

            async def run():
                await manager._accept_sse_async(fd, StubChannel(), ["test_chan"])
                await manager.dispatch_event("other_chan", "ignored")

            loop.run_until_complete(run())

            # Read — should only have headers, no event
            client.setblocking(True)
            client.settimeout(0.2)
            data = client.recv(8192)
            assert b"HTTP/1.1 200 OK" in data
            assert b"data:" not in data

            manager.close_all()
        finally:
            client.close()
            loop.close()

    def test_dead_connection_removed_on_dispatch(self):
        """If a client disconnects, dispatch should remove it."""
        from plain.channels.handler import AsyncConnectionManager

        loop = asyncio.new_event_loop()
        fd, client = _make_socket_pair()
        try:
            manager = AsyncConnectionManager(loop)

            async def run():
                await manager._accept_sse_async(fd, StubChannel(), ["test_chan"])
                assert len(manager._connections) == 1

                # Close client to simulate disconnect
                client.close()

                # Dispatch — should detect dead connection
                await manager.dispatch_event("test_chan", "hello")

                assert len(manager._connections) == 0

            loop.run_until_complete(run())

            manager.close_all()
        finally:
            if not client._closed:
                client.close()
            loop.close()

    def test_close_all(self):
        """close_all() should close all connections."""
        from plain.channels.handler import AsyncConnectionManager

        loop = asyncio.new_event_loop()
        fd1, client1 = _make_socket_pair()
        fd2, client2 = _make_socket_pair()
        try:
            manager = AsyncConnectionManager(loop)

            async def run():
                await manager._accept_sse_async(fd1, StubChannel(), ["a"])
                await manager._accept_sse_async(fd2, StubChannel(), ["b"])
                assert len(manager._connections) == 2

            loop.run_until_complete(run())

            manager.close_all()
            assert len(manager._connections) == 0
        finally:
            client1.close()
            client2.close()
            loop.close()

    def test_transform_modifies_payload(self):
        """Channel.transform() should be applied before sending."""
        from plain.channels.handler import AsyncConnectionManager

        class TransformChannel(Channel):
            path = "/transform/"

            def transform(self, channel_name, payload):
                return {"wrapped": payload}

        loop = asyncio.new_event_loop()
        fd, client = _make_socket_pair()
        try:
            manager = AsyncConnectionManager(loop)

            async def run():
                await manager._accept_sse_async(fd, TransformChannel(), ["x"])
                await manager.dispatch_event("x", "raw")

            loop.run_until_complete(run())

            client.setblocking(True)
            client.settimeout(1.0)
            data = client.recv(8192)
            assert b'{"wrapped": "raw"}' in data

            manager.close_all()
        finally:
            client.close()
            loop.close()

    def test_transform_returning_none_skips_event(self):
        """If transform() returns None, the event should not be sent."""
        from plain.channels.handler import AsyncConnectionManager

        class FilterChannel(Channel):
            path = "/filter/"

            def transform(self, channel_name, payload):
                return None  # Skip all events

        loop = asyncio.new_event_loop()
        fd, client = _make_socket_pair()
        try:
            manager = AsyncConnectionManager(loop)

            async def run():
                await manager._accept_sse_async(fd, FilterChannel(), ["x"])
                await manager.dispatch_event("x", "should_be_filtered")

            loop.run_until_complete(run())

            client.setblocking(True)
            client.settimeout(0.2)
            data = client.recv(8192)
            # Should only have headers, no event data
            assert b"data:" not in data

            manager.close_all()
        finally:
            client.close()
            loop.close()


class TestWebSocketConnection:
    """Integration tests for WebSocketConnection with socket pairs."""

    def _make_masked_frame(self, opcode, payload, fin=True, mask=b"\x01\x02\x03\x04"):
        """Build a client→server masked frame."""
        header = bytearray()
        first_byte = (0x80 if fin else 0x00) | (opcode & 0x0F)
        header.append(first_byte)

        length = len(payload)
        if length < 126:
            header.append(0x80 | length)
        elif length < 65536:
            header.append(0x80 | 126)
            header.extend(struct.pack("!H", length))
        else:
            header.append(0x80 | 127)
            header.extend(struct.pack("!Q", length))

        header.extend(mask)
        masked_payload = _apply_mask(payload, mask)
        return bytes(header) + masked_payload

    def _read_server_frame(self, sock, timeout=1.0):
        """Read a single server→client (unmasked) frame from a socket."""
        sock.setblocking(True)
        sock.settimeout(timeout)
        data = sock.recv(8192)
        if not data:
            return None
        fin = bool(data[0] & 0x80)
        opcode = data[0] & 0x0F
        length = data[1] & 0x7F
        offset = 2
        if length == 126:
            length = struct.unpack("!H", data[2:4])[0]
            offset = 4
        elif length == 127:
            length = struct.unpack("!Q", data[2:10])[0]
            offset = 10
        payload = data[offset : offset + length]
        return {"fin": fin, "opcode": opcode, "payload": payload}

    def test_echo_via_receive(self):
        """Send a text frame, echo channel returns it."""
        from plain.channels.handler import WebSocketConnection

        fd, client = _make_socket_pair()
        loop = asyncio.new_event_loop()
        try:

            async def run():
                conn = WebSocketConnection(fd, EchoChannel(), ["echo"], loop)
                await conn.open()
                conn.start_reading()

                # Give the read loop time to start
                await asyncio.sleep(0.1)

                # Client sends a masked text frame
                frame_data = self._make_masked_frame(OP_TEXT, b"hello ws")
                client.setblocking(True)
                client.sendall(frame_data)

                # Wait for echo response
                await asyncio.sleep(0.3)

                # Client sends close
                close_data = self._make_masked_frame(
                    OP_CLOSE, struct.pack("!H", CLOSE_NORMAL)
                )
                client.sendall(close_data)
                await asyncio.sleep(0.1)

            loop.run_until_complete(run())

            # Read the echo response from the client side
            client.setblocking(True)
            client.settimeout(1.0)
            all_data = client.recv(8192)

            # Should contain the echoed text
            assert b"hello ws" in all_data

        finally:
            client.close()
            loop.close()

    def test_ping_pong(self):
        """Server responds to ping with pong."""
        from plain.channels.handler import WebSocketConnection

        fd, client = _make_socket_pair()
        loop = asyncio.new_event_loop()
        try:

            async def run():
                conn = WebSocketConnection(fd, EchoChannel(), ["echo"], loop)
                await conn.open()
                conn.start_reading()
                await asyncio.sleep(0.1)

                # Client sends ping
                ping_data = self._make_masked_frame(OP_PING, b"ping!")
                client.setblocking(True)
                client.sendall(ping_data)

                await asyncio.sleep(0.2)

                # Send close
                close_data = self._make_masked_frame(
                    OP_CLOSE, struct.pack("!H", CLOSE_NORMAL)
                )
                client.sendall(close_data)
                await asyncio.sleep(0.1)

            loop.run_until_complete(run())

            client.setblocking(True)
            client.settimeout(1.0)
            all_data = client.recv(8192)

            # Should have a pong frame (opcode 0x0A)
            # Find pong in the data
            found_pong = False
            i = 0
            while i < len(all_data):
                opcode = all_data[i] & 0x0F
                if opcode == OP_PONG:
                    found_pong = True
                    break
                # Skip past this frame
                length = all_data[i + 1] & 0x7F
                if length == 126:
                    length = struct.unpack("!H", all_data[i + 2 : i + 4])[0]
                    i += 4 + length
                elif length == 127:
                    length = struct.unpack("!Q", all_data[i + 2 : i + 10])[0]
                    i += 10 + length
                else:
                    i += 2 + length
            assert found_pong, "No pong frame found in response data"

        finally:
            client.close()
            loop.close()

    def test_close_handshake(self):
        """Server echoes close frame."""
        from plain.channels.handler import WebSocketConnection

        fd, client = _make_socket_pair()
        loop = asyncio.new_event_loop()
        try:

            async def run():
                conn = WebSocketConnection(fd, EchoChannel(), ["echo"], loop)
                await conn.open()
                conn.start_reading()
                await asyncio.sleep(0.1)

                # Client initiates close
                close_payload = struct.pack("!H", CLOSE_NORMAL) + b"bye"
                close_data = self._make_masked_frame(OP_CLOSE, close_payload)
                client.setblocking(True)
                client.sendall(close_data)

                await asyncio.sleep(0.3)

            loop.run_until_complete(run())

            client.setblocking(True)
            client.settimeout(1.0)
            all_data = client.recv(8192)

            # Should contain a close frame
            found_close = False
            i = 0
            while i < len(all_data):
                opcode = all_data[i] & 0x0F
                if opcode == OP_CLOSE:
                    found_close = True
                    break
                length = all_data[i + 1] & 0x7F
                if length == 126:
                    length = struct.unpack("!H", all_data[i + 2 : i + 4])[0]
                    i += 4 + length
                elif length == 127:
                    length = struct.unpack("!Q", all_data[i + 2 : i + 10])[0]
                    i += 10 + length
                else:
                    i += 2 + length
            assert found_close, "No close frame in response"

        finally:
            client.close()
            loop.close()

    def test_binary_echo(self):
        """Binary frames are echoed back as binary."""
        from plain.channels.handler import WebSocketConnection

        fd, client = _make_socket_pair()
        loop = asyncio.new_event_loop()
        try:

            async def run():
                conn = WebSocketConnection(fd, EchoChannel(), ["echo"], loop)
                await conn.open()
                conn.start_reading()
                await asyncio.sleep(0.1)

                # Client sends binary frame
                frame_data = self._make_masked_frame(OP_BINARY, b"\x00\x01\xff")
                client.setblocking(True)
                client.sendall(frame_data)
                await asyncio.sleep(0.3)

                # Close
                close_data = self._make_masked_frame(
                    OP_CLOSE, struct.pack("!H", CLOSE_NORMAL)
                )
                client.sendall(close_data)
                await asyncio.sleep(0.1)

            loop.run_until_complete(run())

            client.setblocking(True)
            client.settimeout(1.0)
            all_data = client.recv(8192)

            # Should have a binary frame with our data
            assert b"\x00\x01\xff" in all_data

        finally:
            client.close()
            loop.close()

    def test_server_push_event(self):
        """Server-push via dispatch_event sends a text frame."""
        from plain.channels.handler import AsyncConnectionManager

        fd, client = _make_socket_pair()
        loop = asyncio.new_event_loop()
        try:

            async def run():
                manager = AsyncConnectionManager(loop)
                await manager._accept_ws_async(fd, EchoChannel(), ["echo_chan"])

                await asyncio.sleep(0.1)
                await manager.dispatch_event("echo_chan", "server push")
                await asyncio.sleep(0.2)

                manager.close_all()

            loop.run_until_complete(run())

            client.setblocking(True)
            client.settimeout(1.0)
            all_data = client.recv(8192)

            # Should contain the pushed data as a text frame
            assert b"server push" in all_data

        finally:
            client.close()
            loop.close()


# ===================================================================
# Level 3: Postgres integration tests (need DATABASE_URL)
# ===================================================================


def _can_connect_psycopg() -> bool:
    """Check if we can actually connect to Postgres via psycopg (async)."""
    if "DATABASE_URL" not in os.environ:
        return False
    try:
        import psycopg

        conn = psycopg.connect(os.environ["DATABASE_URL"], autocommit=True)
        conn.close()
        return True
    except Exception:
        return False


needs_postgres = pytest.mark.skipif(
    not _can_connect_psycopg(),
    reason="Cannot connect to Postgres via psycopg — skipping integration tests",
)


@needs_postgres
class TestPostgresListener:
    def test_listener_receives_notification(self):
        """PostgresListener should receive Postgres NOTIFY events."""
        import psycopg

        from plain.channels.handler import AsyncConnectionManager
        from plain.channels.listener import PostgresListener

        conninfo = os.environ["DATABASE_URL"]
        loop = asyncio.new_event_loop()
        try:
            manager = AsyncConnectionManager(loop)
            # Track dispatched events
            dispatched: list[tuple[str, str]] = []

            async def tracking_dispatch(channel_name, payload):
                dispatched.append((channel_name, payload))

            manager.dispatch_event = tracking_dispatch  # type: ignore[assignment]

            async def run():
                listener = PostgresListener(loop, manager, conninfo=conninfo)
                listener.poll_timeout = 0.5
                await listener.start()
                await listener.listen("test_notify_chan")

                # Give the listener time to set up
                await asyncio.sleep(0.3)

                # Send a notification from a separate connection
                notify_conn = await psycopg.AsyncConnection.connect(
                    conninfo, autocommit=True
                )
                await notify_conn.execute(
                    "SELECT pg_notify('test_notify_chan', 'test_payload')"
                )
                await notify_conn.close()

                # Wait for the notification to arrive
                await asyncio.sleep(0.5)

                await listener.stop()

            loop.run_until_complete(run())

            assert len(dispatched) == 1
            assert dispatched[0] == ("test_notify_chan", "test_payload")
        finally:
            loop.close()

    def test_listener_ignores_unsubscribed_channels(self):
        """Notifications on unsubscribed channels should not be dispatched."""
        import psycopg

        from plain.channels.handler import AsyncConnectionManager
        from plain.channels.listener import PostgresListener

        conninfo = os.environ["DATABASE_URL"]
        loop = asyncio.new_event_loop()
        try:
            manager = AsyncConnectionManager(loop)
            dispatched: list[tuple[str, str]] = []

            async def tracking_dispatch(channel_name, payload):
                dispatched.append((channel_name, payload))

            manager.dispatch_event = tracking_dispatch  # type: ignore[assignment]

            async def run():
                listener = PostgresListener(loop, manager, conninfo=conninfo)
                listener.poll_timeout = 0.5
                await listener.start()
                await listener.listen("subscribed_chan")

                await asyncio.sleep(0.3)

                # Send to a channel we're NOT listening on
                notify_conn = await psycopg.AsyncConnection.connect(
                    conninfo, autocommit=True
                )
                await notify_conn.execute(
                    "SELECT pg_notify('other_chan', 'should_not_arrive')"
                )
                await notify_conn.close()

                await asyncio.sleep(0.5)
                await listener.stop()

            loop.run_until_complete(run())

            assert len(dispatched) == 0
        finally:
            loop.close()

    def test_unlisten_stops_notifications(self):
        """After UNLISTEN, notifications should no longer arrive."""
        import psycopg

        from plain.channels.handler import AsyncConnectionManager
        from plain.channels.listener import PostgresListener

        conninfo = os.environ["DATABASE_URL"]
        loop = asyncio.new_event_loop()
        try:
            manager = AsyncConnectionManager(loop)
            dispatched: list[tuple[str, str]] = []

            async def tracking_dispatch(channel_name, payload):
                dispatched.append((channel_name, payload))

            manager.dispatch_event = tracking_dispatch  # type: ignore[assignment]

            async def run():
                listener = PostgresListener(loop, manager, conninfo=conninfo)
                listener.poll_timeout = 0.5
                await listener.start()
                await listener.listen("temp_chan")
                await asyncio.sleep(0.3)

                # Send first notification — should arrive
                notify_conn = await psycopg.AsyncConnection.connect(
                    conninfo, autocommit=True
                )
                await notify_conn.execute("SELECT pg_notify('temp_chan', 'first')")
                await asyncio.sleep(0.5)
                assert len(dispatched) == 1

                # Unlisten
                await listener.unlisten("temp_chan")
                await asyncio.sleep(0.1)

                # Send second notification — should NOT arrive
                await notify_conn.execute("SELECT pg_notify('temp_chan', 'second')")
                await asyncio.sleep(0.5)
                await notify_conn.close()

                assert len(dispatched) == 1  # Still just the first one

                await listener.stop()

            loop.run_until_complete(run())
        finally:
            loop.close()


@needs_postgres
class TestFullPipeline:
    def test_notify_to_sse_client(self):
        """Full pipeline: pg_notify → PostgresListener → AsyncConnectionManager → SSE socket."""
        import psycopg

        from plain.channels.handler import AsyncConnectionManager
        from plain.channels.listener import PostgresListener

        conninfo = os.environ["DATABASE_URL"]
        loop = asyncio.new_event_loop()
        fd, client = _make_socket_pair()
        try:

            async def run():
                manager = AsyncConnectionManager(loop)

                # Wire up the listener directly (bypassing start() which auto-creates one)
                listener = PostgresListener(loop, manager, conninfo=conninfo)
                listener.poll_timeout = 0.5
                manager._listener = listener
                await listener.start()

                # Accept an SSE connection
                await manager._accept_sse_async(fd, StubChannel(), ["test_chan"])

                # Subscribe the channel in the listener
                await listener.listen("test_chan")
                await asyncio.sleep(0.3)

                # Send a notification from a separate Postgres connection
                notify_conn = await psycopg.AsyncConnection.connect(
                    conninfo, autocommit=True
                )
                await notify_conn.execute("SELECT pg_notify('test_chan', 'real_event')")
                await notify_conn.close()

                # Wait for it to propagate
                await asyncio.sleep(0.5)

                await listener.stop()
                manager.close_all()

            loop.run_until_complete(run())

            # Read everything the SSE client received
            client.setblocking(True)
            client.settimeout(1.0)
            data = client.recv(8192)

            # Should have HTTP headers
            assert b"HTTP/1.1 200 OK" in data
            assert b"text/event-stream" in data

            # Should have the event
            assert b"event: test_chan" in data
            assert b"data: real_event" in data

        finally:
            client.close()
            loop.close()
