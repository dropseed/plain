"""Tests for WebSocket protocol implementation and view integration."""

from __future__ import annotations

import asyncio
import struct

import pytest

from plain.server.protocols.websocket import (
    CLOSE_NO_STATUS,
    CLOSE_NORMAL,
    CLOSE_PROTOCOL_ERROR,
    OP_BINARY,
    OP_CLOSE,
    OP_CONTINUATION,
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
from plain.websockets import (
    WebSocketConnection,
    WebSocketHandler,
)

# ---------------------------------------------------------------------------
# Frame encoding/decoding
# ---------------------------------------------------------------------------


class TestFrameEncoding:
    def test_encode_text_frame(self):
        frame = encode_frame(OP_TEXT, b"hello")
        assert frame[0] == 0x81  # FIN + TEXT
        assert frame[1] == 5
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

    def test_encode_pong(self):
        frame = encode_frame(OP_PONG, b"data")
        assert frame[0] == 0x8A  # FIN + PONG

    def test_encode_close(self):
        frame = encode_close(CLOSE_NORMAL, "bye")
        assert frame[0] == 0x88  # FIN + CLOSE
        payload = frame[2:]
        code = struct.unpack("!H", payload[:2])[0]
        assert code == 1000
        assert payload[2:] == b"bye"


# ---------------------------------------------------------------------------
# Masking
# ---------------------------------------------------------------------------


class TestApplyMask:
    def test_roundtrip(self):
        mask = b"\x37\xfa\x21\x3d"
        data = b"Hello"
        masked = _apply_mask(data, mask)
        assert _apply_mask(masked, mask) == data

    def test_empty(self):
        assert _apply_mask(b"", b"\x01\x02\x03\x04") == b""

    def test_small(self):
        mask = b"\xaa\xbb\xcc\xdd"
        data = b"Hi"
        masked = _apply_mask(data, mask)
        assert _apply_mask(masked, mask) == data

    def test_exactly_8_bytes(self):
        mask = b"\x12\x34\x56\x78"
        data = b"12345678"
        masked = _apply_mask(data, mask)
        assert _apply_mask(masked, mask) == data

    def test_large_payload(self):
        mask = b"\xde\xad\xbe\xef"
        data = b"A" * 2000
        masked = _apply_mask(data, mask)
        assert _apply_mask(masked, mask) == data
        assert len(masked) == 2000

    def test_invalid_mask_length(self):
        with pytest.raises(ValueError, match="4 bytes"):
            _apply_mask(b"data", b"\x01\x02\x03")


# ---------------------------------------------------------------------------
# Close payload parsing
# ---------------------------------------------------------------------------


class TestClosePayload:
    def test_normal_close(self):
        payload = struct.pack("!H", 1000) + b"goodbye"
        result = parse_close_payload(payload)
        assert result.code == 1000
        assert result.reason == "goodbye"

    def test_empty_payload(self):
        result = parse_close_payload(b"")
        assert result.code == CLOSE_NO_STATUS

    def test_single_byte(self):
        result = parse_close_payload(b"\x00")
        assert result.code == CLOSE_PROTOCOL_ERROR


# ---------------------------------------------------------------------------
# Handshake validation
# ---------------------------------------------------------------------------


class TestHandshakeValidation:
    def test_valid_upgrade(self):
        headers = [
            ("CONNECTION", "Upgrade"),
            ("UPGRADE", "websocket"),
            ("SEC-WEBSOCKET-KEY", "dGhlIHNhbXBsZSBub25jZQ=="),
            ("SEC-WEBSOCKET-VERSION", "13"),
        ]
        result = validate_handshake_headers(headers)
        assert result.is_websocket is True
        assert result.ws_key == "dGhlIHNhbXBsZSBub25jZQ=="
        assert result.error == ""
        assert result.permessage_deflate is False

    def test_permessage_deflate_negotiation(self):
        headers = [
            ("CONNECTION", "Upgrade"),
            ("UPGRADE", "websocket"),
            ("SEC-WEBSOCKET-KEY", "dGhlIHNhbXBsZSBub25jZQ=="),
            ("SEC-WEBSOCKET-VERSION", "13"),
            ("SEC-WEBSOCKET-EXTENSIONS", "permessage-deflate"),
        ]
        result = validate_handshake_headers(headers)
        assert result.is_websocket is True
        assert result.permessage_deflate is True

    def test_not_websocket(self):
        headers = [("CONNECTION", "keep-alive")]
        result = validate_handshake_headers(headers)
        assert result.is_websocket is False

    def test_wrong_version(self):
        headers = [
            ("CONNECTION", "Upgrade"),
            ("UPGRADE", "websocket"),
            ("SEC-WEBSOCKET-KEY", "dGhlIHNhbXBsZSBub25jZQ=="),
            ("SEC-WEBSOCKET-VERSION", "8"),
        ]
        result = validate_handshake_headers(headers)
        assert result.is_websocket is True
        assert "version" in result.error.lower()

    def test_missing_key(self):
        headers = [
            ("CONNECTION", "Upgrade"),
            ("UPGRADE", "websocket"),
            ("SEC-WEBSOCKET-VERSION", "13"),
        ]
        result = validate_handshake_headers(headers)
        assert result.is_websocket is True
        assert "Key" in result.error

    def test_compute_accept_key(self):
        key = "dGhlIHNhbXBsZSBub25jZQ=="
        expected = "s3pPLMBiTxaQ9kYGzzhZRbK+xOo="
        assert compute_accept_key(key) == expected

    def test_build_accept_response(self):
        resp = build_accept_response("dGhlIHNhbXBsZSBub25jZQ==")
        assert b"HTTP/1.1 101 Switching Protocols" in resp
        assert b"Upgrade: websocket" in resp
        assert b"Connection: Upgrade" in resp
        assert b"s3pPLMBiTxaQ9kYGzzhZRbK+xOo=" in resp


# ---------------------------------------------------------------------------
# Frame reading (async)
# ---------------------------------------------------------------------------


def _make_masked_frame(opcode, payload, fin=True, mask=b"\x01\x02\x03\x04"):
    """Build a client->server masked frame."""
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


async def _read_frame_from_data(data: bytes):
    reader = asyncio.StreamReader()
    reader.feed_data(data)
    return await read_frame(reader)


class TestReadFrame:
    def test_read_text_frame(self):
        data = _make_masked_frame(OP_TEXT, b"hello")
        frame = asyncio.run(_read_frame_from_data(data))
        assert frame.fin is True
        assert frame.opcode == OP_TEXT
        assert frame.payload == b"hello"

    def test_read_binary_frame(self):
        data = _make_masked_frame(OP_BINARY, b"\x00\x01\x02")
        frame = asyncio.run(_read_frame_from_data(data))
        assert frame.opcode == OP_BINARY
        assert frame.payload == b"\x00\x01\x02"

    def test_read_ping_frame(self):
        data = _make_masked_frame(OP_PING, b"")
        frame = asyncio.run(_read_frame_from_data(data))
        assert frame.opcode == OP_PING

    def test_read_close_frame(self):
        close_payload = struct.pack("!H", 1000) + b"bye"
        data = _make_masked_frame(OP_CLOSE, close_payload)
        frame = asyncio.run(_read_frame_from_data(data))
        assert frame.opcode == OP_CLOSE
        close = parse_close_payload(frame.payload)
        assert close.code == 1000
        assert close.reason == "bye"

    def test_reject_unmasked_frame(self):
        data = bytes([0x81, 0x05]) + b"hello"
        with pytest.raises(ValueError, match="not masked"):
            asyncio.run(_read_frame_from_data(data))

    def test_reject_rsv_bits(self):
        header = bytes([0xC1, 0x80, 0x01, 0x02, 0x03, 0x04])
        with pytest.raises(ValueError, match="RSV"):
            asyncio.run(_read_frame_from_data(header))

    def test_fragmented_text(self):
        frame1 = _make_masked_frame(OP_TEXT, b"hel", fin=False)
        frame2 = _make_masked_frame(0x0, b"lo", fin=True)

        async def run():
            reader = asyncio.StreamReader()
            reader.feed_data(frame1 + frame2)
            f1 = await read_frame(reader)
            f2 = await read_frame(reader)
            return f1, f2

        f1, f2 = asyncio.run(run())
        assert f1.fin is False
        assert f1.opcode == OP_TEXT
        assert f1.payload == b"hel"
        assert f2.fin is True
        assert f2.opcode == 0x0
        assert f2.payload == b"lo"

    def test_read_medium_payload(self):
        payload = b"x" * 200
        data = _make_masked_frame(OP_BINARY, payload)
        frame = asyncio.run(_read_frame_from_data(data))
        assert frame.payload == payload

    def test_reject_unknown_opcode(self):
        header = bytes([0x85, 0x80, 0x01, 0x02, 0x03, 0x04])
        with pytest.raises(ValueError, match="Unknown opcode"):
            asyncio.run(_read_frame_from_data(header))

    def test_reject_fragmented_control_frame(self):
        data = _make_masked_frame(OP_PING, b"", fin=False)
        with pytest.raises(ValueError, match="Fragmented control"):
            asyncio.run(_read_frame_from_data(data))


# ---------------------------------------------------------------------------
# read_messages integration tests
# ---------------------------------------------------------------------------


class _FakeWriter:
    """Minimal writer for testing — records written data."""

    def __init__(self):
        self.written = bytearray()

    def write(self, data: bytes) -> None:
        self.written.extend(data)

    def close(self) -> None:
        pass

    def is_closing(self) -> bool:
        return False

    async def drain(self) -> None:
        pass

    async def wait_closed(self) -> None:
        pass


def _make_reader_writer(*frames: bytes) -> tuple[asyncio.StreamReader, _FakeWriter]:
    """Create reader pre-loaded with frame data and a fake writer.

    Must be called inside a running event loop (asyncio.run).
    """
    reader = asyncio.StreamReader()
    reader.feed_data(b"".join(frames))
    reader.feed_eof()
    return reader, _FakeWriter()


class TestReadMessages:
    """Test message iteration via WebSocketConnection.__aiter__."""

    def test_single_text_message(self):
        async def run():
            reader, writer = _make_reader_writer(
                _make_masked_frame(OP_TEXT, b"hello"),
                _make_masked_frame(OP_CLOSE, struct.pack("!H", 1000)),
            )
            ws = WebSocketConnection(reader, writer)
            return [msg async for msg in ws]

        assert asyncio.run(run()) == ["hello"]

    def test_binary_message(self):
        data = b"\x00\x01\x02"

        async def run():
            reader, writer = _make_reader_writer(
                _make_masked_frame(OP_BINARY, data),
                _make_masked_frame(OP_CLOSE, struct.pack("!H", 1000)),
            )
            ws = WebSocketConnection(reader, writer)
            return [msg async for msg in ws]

        assert asyncio.run(run()) == [data]

    def test_multiple_messages(self):
        async def run():
            reader, writer = _make_reader_writer(
                _make_masked_frame(OP_TEXT, b"one"),
                _make_masked_frame(OP_TEXT, b"two"),
                _make_masked_frame(OP_TEXT, b"three"),
                _make_masked_frame(OP_CLOSE, struct.pack("!H", 1000)),
            )
            ws = WebSocketConnection(reader, writer)
            return [msg async for msg in ws]

        assert asyncio.run(run()) == ["one", "two", "three"]

    def test_fragmented_text(self):
        async def run():
            reader, writer = _make_reader_writer(
                _make_masked_frame(OP_TEXT, b"hel", fin=False),
                _make_masked_frame(OP_CONTINUATION, b"lo", fin=True),
                _make_masked_frame(OP_CLOSE, struct.pack("!H", 1000)),
            )
            ws = WebSocketConnection(reader, writer)
            return [msg async for msg in ws]

        assert asyncio.run(run()) == ["hello"]

    def test_ping_pong(self):
        async def run():
            reader, writer = _make_reader_writer(
                _make_masked_frame(OP_PING, b"ping-data"),
                _make_masked_frame(OP_TEXT, b"msg"),
                _make_masked_frame(OP_CLOSE, struct.pack("!H", 1000)),
            )
            ws = WebSocketConnection(reader, writer)
            messages = [msg async for msg in ws]
            return messages, bytes(writer.written)

        messages, written = asyncio.run(run())
        assert messages == ["msg"]
        pong = encode_frame(OP_PONG, b"ping-data")
        assert pong in written

    def test_connection_eof(self):
        """EOF without close frame — yields nothing, no crash."""

        async def run():
            reader = asyncio.StreamReader()
            reader.feed_eof()
            writer = _FakeWriter()
            ws = WebSocketConnection(reader, writer)
            return [msg async for msg in ws]

        assert asyncio.run(run()) == []

    def test_close_no_status(self):
        """Close frame with no payload — replies with code 1000."""

        async def run():
            reader, writer = _make_reader_writer(
                _make_masked_frame(OP_CLOSE, b""),
            )
            ws = WebSocketConnection(reader, writer)
            return [msg async for msg in ws]

        assert asyncio.run(run()) == []


# ---------------------------------------------------------------------------
# View-level tests
# ---------------------------------------------------------------------------


class TestHandlerClassDetection:
    def test_path_stores_view_class(self):
        """path() stores WebSocketHandler as view_class."""
        from plain.urls import path

        class MyHandler(WebSocketHandler):
            async def authorize(self):
                return True

        url_pattern = path("ws/", MyHandler)
        assert url_pattern.view_class is MyHandler

    def test_view_class_is_websocket_handler(self):
        from plain.urls import path

        class MyHandler(WebSocketHandler):
            async def authorize(self):
                return True

        url_pattern = path("ws/", MyHandler)
        assert issubclass(url_pattern.view_class, WebSocketHandler)


class TestWebSocketConnection:
    def test_send_text(self):
        async def run():
            writer = _FakeWriter()
            ws = WebSocketConnection(asyncio.StreamReader(), writer)
            await ws.send("hello")
            return bytes(writer.written)

        assert asyncio.run(run()) == encode_frame(OP_TEXT, b"hello")

    def test_send_binary(self):
        async def run():
            writer = _FakeWriter()
            ws = WebSocketConnection(asyncio.StreamReader(), writer)
            await ws.send(b"\x00\x01")
            return bytes(writer.written)

        assert asyncio.run(run()) == encode_frame(OP_BINARY, b"\x00\x01")

    def test_send_json(self):
        async def run():
            writer = _FakeWriter()
            ws = WebSocketConnection(asyncio.StreamReader(), writer)
            await ws.send_json({"key": "value"})
            return bytes(writer.written)

        assert asyncio.run(run()) == encode_frame(OP_TEXT, b'{"key": "value"}')

    def test_close(self):
        async def run():
            writer = _FakeWriter()
            ws = WebSocketConnection(asyncio.StreamReader(), writer)
            await ws.close(1000, "bye")
            return ws.closed, bytes(writer.written)

        closed, written = asyncio.run(run())
        assert closed is True
        assert written == encode_close(1000, "bye")

    def test_close_idempotent(self):
        async def run():
            writer = _FakeWriter()
            ws = WebSocketConnection(asyncio.StreamReader(), writer)
            await ws.close()
            first_written = len(writer.written)
            await ws.close()
            return len(writer.written) == first_written

        assert asyncio.run(run())

    def test_send_after_close_is_noop(self):
        async def run():
            writer = _FakeWriter()
            ws = WebSocketConnection(asyncio.StreamReader(), writer)
            await ws.close()
            written_after_close = len(writer.written)
            await ws.send("ignored")
            return len(writer.written) == written_after_close

        assert asyncio.run(run())
