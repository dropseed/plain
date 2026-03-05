"""Tests for the plain.realtime infrastructure.

Tests are organized as unit tests for SSE formatting and WebSocket framing.
Integration tests for the full SSE/WebSocket pipeline require a running server.
"""

import asyncio
import struct

import pytest

from plain.realtime.channel import SSEView
from plain.server.protocols.sse import SSE_HEADERS, format_sse_comment, format_sse_event
from plain.server.protocols.websocket import (
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
# Level 1: Unit tests — no infrastructure needed
# ---------------------------------------------------------------------------


class TestSSEFormatting:
    def test_format_event_basic(self):
        result = format_sse_event("hello")
        assert b"data: hello\n\n" == result

    def test_format_event_multiline(self):
        result = format_sse_event("line1\nline2")
        assert b"data: line1\ndata: line2\n\n" == result

    def test_format_event_with_event_type(self):
        result = format_sse_event("data", event="update")
        assert b"event: update\ndata: data\n\n" == result

    def test_format_event_with_id(self):
        result = format_sse_event("data", event_id="42")
        assert b"id: 42\ndata: data\n\n" == result

    def test_format_event_all_fields(self):
        result = format_sse_event("data", event="msg", event_id="1")
        assert b"event: msg\n" in result
        assert b"id: 1\n" in result
        assert b"data: data\n\n" in result

    def test_format_event_empty_data(self):
        result = format_sse_event("")
        assert b"data: \n\n" == result

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
        assert SSE_HEADERS["Cache-Control"] == "no-cache"
        assert SSE_HEADERS["X-Accel-Buffering"] == "no"


class TestSSEViewBaseClass:
    def test_default_authorize(self):
        ch = SSEView()
        assert ch.authorize() is True

    def test_default_subscribe(self):
        ch = SSEView()
        assert ch.subscribe() == []

    def test_default_transform(self):
        ch = SSEView()
        assert ch.transform("chan", "payload") == "payload"


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
        expected = "s3pPLMBiTxaQ9kYGzzhZRbK+xOo="
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
        assert b"s3pPLMBiTxaQ9kYGzzhZRbK+xOo=" in resp


class TestReadFrame:
    """Unit tests for async frame reading."""

    def _make_masked_frame(self, opcode, payload, fin=True, mask=b"\x01\x02\x03\x04"):
        """Build a client->server masked frame."""
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
