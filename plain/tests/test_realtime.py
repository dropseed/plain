"""Tests for SSE formatting, WebSocket framing, and H2 handler protocols.

Integration tests for the full SSE/WebSocket pipeline require a running server.
"""

from __future__ import annotations

import asyncio
import struct

import pytest

from plain.server.http.h2handler import (
    H2Request,
    H2Stream,
    _build_h2_response_headers,
    _build_http_request,
    _extract_headers_from_stream,
)
from plain.server.protocols.sse import (
    SSE_HEADERS,
    _sanitize_field,
    format_sse_comment,
    format_sse_event,
)
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

    def test_sanitize_field_strips_newlines(self):
        assert _sanitize_field("evil\ninjection") == "evilinjection"
        assert _sanitize_field("evil\r\ninjection") == "evilinjection"
        assert _sanitize_field("evil\rinjection") == "evilinjection"

    def test_format_event_with_json_dict(self):
        result = format_sse_event({"key": "value"})
        assert b'data: {"key": "value"}\n\n' == result

    def test_format_event_with_json_list(self):
        result = format_sse_event([1, 2, 3])
        assert b"data: [1, 2, 3]\n\n" == result

    def test_format_event_with_retry(self):
        result = format_sse_event("data", retry=5000)
        assert b"retry: 5000\n" in result
        assert b"data: data\n\n" in result

    def test_event_type_injection_blocked(self):
        """Newlines in event field are stripped to prevent SSE injection."""
        result = format_sse_event("data", event="legit\ndata: injected")
        assert b"event: legitdata: injected\n" in result
        # The injected "data:" is on the same line as event, not a separate field
        assert result.count(b"data:") == 2  # one from event field, one from actual data

    def test_data_bare_cr_normalized(self):
        """Bare \\r in data is normalized to \\n so it splits correctly."""
        result = format_sse_event("line1\rline2")
        assert b"data: line1\ndata: line2\n\n" == result

    def test_data_crlf_normalized(self):
        """\\r\\n in data is normalized to \\n."""
        result = format_sse_event("line1\r\nline2")
        assert b"data: line1\ndata: line2\n\n" == result


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


def _make_masked_frame(opcode, payload, fin=True, mask=b"\x01\x02\x03\x04"):
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


async def _read_frame_from_data(data: bytes):
    """Helper: feed data into a StreamReader and read one frame."""
    reader = asyncio.StreamReader()
    reader.feed_data(data)
    return await read_frame(reader)


class TestReadFrame:
    """Unit tests for async frame reading."""

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
        """Client frames must be masked."""
        data = bytes([0x81, 0x05]) + b"hello"  # no mask bit
        with pytest.raises(ValueError, match="not masked"):
            asyncio.run(_read_frame_from_data(data))

    def test_reject_rsv_bits(self):
        """RSV bits must be 0 (no extensions)."""
        # FIN+RSV1+TEXT, masked, 0 length
        header = bytes([0xC1, 0x80, 0x01, 0x02, 0x03, 0x04])
        with pytest.raises(ValueError, match="RSV"):
            asyncio.run(_read_frame_from_data(header))

    def test_fragmented_text(self):
        """Test reading fragmented message (first + continuation)."""
        frame1 = _make_masked_frame(OP_TEXT, b"hel", fin=False)
        frame2 = _make_masked_frame(0x0, b"lo", fin=True)  # continuation

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
        assert f2.opcode == 0x0  # continuation
        assert f2.payload == b"lo"

    def test_read_medium_payload(self):
        """Test reading a frame with 2-byte extended length."""
        payload = b"x" * 200
        data = _make_masked_frame(OP_BINARY, payload)
        frame = asyncio.run(_read_frame_from_data(data))
        assert frame.payload == payload

    def test_reject_unknown_opcode(self):
        """Unknown opcodes should be rejected."""
        # opcode 0x5 is reserved
        header = bytes([0x85, 0x80, 0x01, 0x02, 0x03, 0x04])
        with pytest.raises(ValueError, match="Unknown opcode"):
            asyncio.run(_read_frame_from_data(header))

    def test_reject_fragmented_control_frame(self):
        """Control frames must not be fragmented."""
        # PING with fin=False
        data = _make_masked_frame(OP_PING, b"", fin=False)
        with pytest.raises(ValueError, match="Fragmented control"):
            asyncio.run(_read_frame_from_data(data))


class TestApplyMaskPerformance:
    """Test masking correctness across payload sizes."""

    def test_mask_empty(self):
        assert _apply_mask(b"", b"\x01\x02\x03\x04") == b""

    def test_mask_small(self):
        """Payloads smaller than 8 bytes use the remainder path."""
        mask = b"\xaa\xbb\xcc\xdd"
        data = b"Hi"
        masked = _apply_mask(data, mask)
        assert _apply_mask(masked, mask) == data

    def test_mask_exactly_8_bytes(self):
        mask = b"\x12\x34\x56\x78"
        data = b"12345678"
        masked = _apply_mask(data, mask)
        assert _apply_mask(masked, mask) == data

    def test_mask_large_payload(self):
        """Exercise the memoryview path for payloads > 1024 bytes."""
        mask = b"\xde\xad\xbe\xef"
        data = b"A" * 2000
        masked = _apply_mask(data, mask)
        assert _apply_mask(masked, mask) == data
        assert len(masked) == 2000

    def test_mask_invalid_length(self):
        with pytest.raises(ValueError, match="4 bytes"):
            _apply_mask(b"data", b"\x01\x02\x03")


# ---------------------------------------------------------------------------
# H2 handler unit tests
# ---------------------------------------------------------------------------


class TestH2Stream:
    def test_stream_accumulates_data(self):
        stream = H2Stream(1)
        stream.headers = [(":method", "POST"), (":path", "/upload")]
        stream.data.write(b"hello ")
        stream.data_size += 6
        stream.data.write(b"world")
        stream.data_size += 5
        stream.data.seek(0)
        assert stream.data.read() == b"hello world"
        assert stream.data_size == 11


class TestH2ExtractHeaders:
    def test_basic_extraction(self):
        stream = H2Stream(1)
        stream.headers = [
            (":method", "GET"),
            (":path", "/foo?bar=1"),
            (":authority", "example.com"),
            (":scheme", "https"),
            ("content-type", "text/html"),
        ]
        method, path, authority, scheme, raw_headers = _extract_headers_from_stream(
            stream, "http"
        )
        assert method == "GET"
        assert path == "/foo?bar=1"
        assert authority == "example.com"
        assert scheme == "https"
        assert ("CONTENT-TYPE", "text/html") in raw_headers

    def test_authority_becomes_host(self):
        stream = H2Stream(1)
        stream.headers = [
            (":method", "GET"),
            (":path", "/"),
            (":authority", "example.com"),
        ]
        _, _, _, _, raw_headers = _extract_headers_from_stream(stream, "https")
        assert ("HOST", "example.com") in raw_headers

    def test_existing_host_not_duplicated(self):
        stream = H2Stream(1)
        stream.headers = [
            (":method", "GET"),
            (":path", "/"),
            (":authority", "example.com"),
            ("host", "example.com"),
        ]
        _, _, _, _, raw_headers = _extract_headers_from_stream(stream, "https")
        host_count = sum(1 for n, _ in raw_headers if n == "HOST")
        assert host_count == 1


class TestH2BuildHttpRequest:
    def test_builds_request(self):
        request = _build_http_request(
            method="POST",
            path_info="/api/data",
            query="key=val",
            scheme="https",
            raw_headers=[("CONTENT-TYPE", "application/json")],
            authority="api.example.com:8443",
            client=("127.0.0.1", 5000),
            server=("0.0.0.0", 8443),
        )
        assert request.method == "POST"
        assert request.path_info == "/api/data"
        assert request.query_string == "key=val"
        assert request.server_scheme == "https"
        assert request.headers["Content-Type"] == "application/json"

    def test_server_from_authority_fallback(self):
        """When server is not a tuple, falls back to authority."""
        request = _build_http_request(
            method="GET",
            path_info="/",
            query="",
            scheme="https",
            raw_headers=[],
            authority="example.com:443",
            client="127.0.0.1",
            server="unix:/tmp/sock",
        )
        assert request.server_name == "example.com"
        assert request.server_port == "443"


class TestH2ResponseHeaders:
    def test_skip_hop_by_hop(self):
        """H2 responses must not include hop-by-hop headers."""

        class FakeResponse:
            status_code = 200

            def header_items(self):
                return [
                    ("Content-Type", "text/html"),
                    ("Connection", "keep-alive"),
                    ("Transfer-Encoding", "chunked"),
                    ("X-Custom", "value"),
                ]

        headers = _build_h2_response_headers(FakeResponse())
        header_names = [n for n, _ in headers]
        assert ":status" in header_names
        assert "connection" not in header_names
        assert "transfer-encoding" not in header_names
        assert "x-custom" in header_names

    def test_status_header(self):
        class FakeResponse:
            status_code = 404

            def header_items(self):
                return []

        headers = _build_h2_response_headers(FakeResponse())
        assert (":status", "404") in headers


class TestH2Request:
    def test_should_close_always_false(self):
        req = H2Request(
            method="GET",
            path="/",
            query="",
            headers=[],
            peer_addr=("127.0.0.1", 1234),
            scheme="https",
        )
        assert req.should_close() is False

    def test_uri_with_query(self):
        req = H2Request(
            method="GET",
            path="/search",
            query="q=test",
            headers=[],
            peer_addr=("127.0.0.1", 1234),
            scheme="https",
        )
        assert req.uri == "/search?q=test"

    def test_uri_without_query(self):
        req = H2Request(
            method="GET",
            path="/",
            query="",
            headers=[],
            peer_addr=("127.0.0.1", 1234),
            scheme="https",
        )
        assert req.uri == "/"
