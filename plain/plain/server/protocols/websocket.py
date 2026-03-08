"""WebSocket frame protocol implementation (RFC 6455).

Handles frame parsing, serialization, masking, the opening handshake,
and the close handshake. Includes permessage-deflate compression
(RFC 7692). Used internally by WebSocketConnection.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import struct
import zlib
from collections.abc import AsyncIterator
from typing import Any, NamedTuple

# WebSocket opcodes (RFC 6455 Section 5.2)
OP_CONTINUATION = 0x0
OP_TEXT = 0x1
OP_BINARY = 0x2
OP_CLOSE = 0x8
OP_PING = 0x9
OP_PONG = 0xA

# Magic GUID for Sec-WebSocket-Accept (RFC 6455 Section 4.2.2)
_WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

# Close status codes (RFC 6455 Section 7.4.1)
CLOSE_NORMAL = 1000
CLOSE_GOING_AWAY = 1001
CLOSE_PROTOCOL_ERROR = 1002
CLOSE_UNSUPPORTED_DATA = 1003
CLOSE_NO_STATUS = 1005
CLOSE_ABNORMAL = 1006
CLOSE_INVALID_PAYLOAD = 1007
CLOSE_POLICY_VIOLATION = 1008
CLOSE_MESSAGE_TOO_BIG = 1009
CLOSE_MANDATORY_EXTENSION = 1010
CLOSE_INTERNAL_ERROR = 1011

# Maximum frame payload size (64 KiB for control frames is per-spec 125,
# but we allow larger data frames)
MAX_CONTROL_PAYLOAD = 125
MAX_DATA_PAYLOAD = 16 * 1024 * 1024  # 16 MiB


class Frame(NamedTuple):
    fin: bool
    opcode: int
    payload: bytes
    rsv1: bool = False


class CloseReason(NamedTuple):
    code: int
    reason: str


def compute_accept_key(key: str) -> str:
    """Compute the Sec-WebSocket-Accept value for the opening handshake."""
    digest = hashlib.sha1((key + _WS_GUID).encode()).digest()
    return base64.b64encode(digest).decode()


def _apply_mask(data: bytes, mask: bytes) -> bytes:
    """Apply XOR masking to data (RFC 6455 Section 5.3).

    Uses a repeating mask key XOR'd in 8-byte chunks for speed.
    On a 16 MiB payload this is ~10x faster than byte-at-a-time.
    """
    if len(mask) != 4:
        raise ValueError("Mask must be 4 bytes")
    n = len(data)
    if n == 0:
        return b""

    result = bytearray(data)
    mask8 = int.from_bytes(mask * 2, "big")

    # Process 8 bytes at a time.  Use memoryview for reads to avoid
    # repeated slicing copies on large payloads.
    mv = memoryview(result)
    i = 0
    while i + 8 <= n:
        chunk = int.from_bytes(mv[i : i + 8], "big")
        chunk ^= mask8
        result[i : i + 8] = chunk.to_bytes(8, "big")
        i += 8

    # Handle remaining bytes
    for j in range(i, n):
        result[j] ^= mask[j % 4]

    return bytes(result)


def encode_frame(
    opcode: int,
    payload: bytes = b"",
    fin: bool = True,
    rsv1: bool = False,
) -> bytes:
    """Encode a WebSocket frame for sending (server->client, no masking)."""
    header = bytearray()

    # First byte: FIN + RSV1 + opcode
    first_byte = (0x80 if fin else 0x00) | (0x40 if rsv1 else 0x00) | (opcode & 0x0F)
    header.append(first_byte)

    # Second byte: no mask + payload length
    length = len(payload)
    if length < 126:
        header.append(length)
    elif length < 65536:
        header.append(126)
        header.extend(struct.pack("!H", length))
    else:
        header.append(127)
        header.extend(struct.pack("!Q", length))

    return bytes(header) + payload


def encode_close(code: int = CLOSE_NORMAL, reason: str = "") -> bytes:
    """Encode a close frame payload."""
    payload = struct.pack("!H", code) + reason.encode("utf-8")
    return encode_frame(OP_CLOSE, payload)


def parse_close_payload(payload: bytes) -> CloseReason:
    """Parse a close frame payload into (code, reason).

    Returns CLOSE_PROTOCOL_ERROR for invalid payloads (wrong length,
    invalid close code, or invalid UTF-8 in reason).
    """
    if len(payload) == 0:
        return CloseReason(CLOSE_NO_STATUS, "")
    if len(payload) == 1:
        # Invalid: close payload must be 0 or >= 2 bytes
        return CloseReason(CLOSE_PROTOCOL_ERROR, "")
    code = struct.unpack("!H", payload[:2])[0]
    if not _is_valid_close_code(code):
        return CloseReason(CLOSE_PROTOCOL_ERROR, "Invalid close code")
    try:
        reason = payload[2:].decode("utf-8")
    except UnicodeDecodeError:
        return CloseReason(CLOSE_PROTOCOL_ERROR, "Invalid UTF-8 in close reason")
    return CloseReason(code, reason)


def _is_valid_close_code(code: int) -> bool:
    """Check if a close code is valid per RFC 6455 Section 7.4."""
    # 1000-1003 are valid
    if 1000 <= code <= 1003:
        return True
    # 1007-1014 are valid (1012-1014 are IANA-registered extensions)
    if 1007 <= code <= 1014:
        return True
    # 3000-3999 reserved for libraries/frameworks/applications
    if 3000 <= code <= 3999:
        return True
    # 4000-4999 reserved for private use
    if 4000 <= code <= 4999:
        return True
    # Everything else is invalid (0-999, 1004-1006, 1015-2999, 5000+)
    return False


async def read_frame(
    reader: asyncio.StreamReader,
    max_payload: int = MAX_DATA_PAYLOAD,
    permessage_deflate: bool = False,
) -> Frame:
    """Read and decode a single WebSocket frame from the stream.

    Client->server frames must be masked (RFC 6455 Section 5.1).
    Raises ConnectionError on EOF, ValueError on protocol violations.
    """
    # Read first 2 bytes
    data = await reader.readexactly(2)
    first_byte, second_byte = data[0], data[1]

    fin = bool(first_byte & 0x80)
    rsv1 = bool(first_byte & 0x40)
    rsv2 = bool(first_byte & 0x20)
    rsv3 = bool(first_byte & 0x10)
    opcode = first_byte & 0x0F
    masked = bool(second_byte & 0x80)
    length = second_byte & 0x7F

    # RSV1 is allowed when permessage-deflate is negotiated
    if rsv1 and not permessage_deflate:
        raise ValueError("Non-zero RSV1 bit without compression")
    if rsv2 or rsv3:
        raise ValueError("Non-zero RSV2/RSV3 bits")

    # Client frames must be masked
    if not masked:
        raise ValueError("Client frame is not masked")

    # Validate opcode
    if opcode not in (OP_CONTINUATION, OP_TEXT, OP_BINARY, OP_CLOSE, OP_PING, OP_PONG):
        raise ValueError(f"Unknown opcode: {opcode:#x}")

    # Control frames (opcode >= 0x8) must be fin and <= 125 bytes
    if opcode >= 0x8:
        if not fin:
            raise ValueError("Fragmented control frame")
        if length > MAX_CONTROL_PAYLOAD:
            raise ValueError(f"Control frame payload too long: {length}")

    # Extended payload length
    if length == 126:
        data = await reader.readexactly(2)
        length = struct.unpack("!H", data)[0]
    elif length == 127:
        data = await reader.readexactly(8)
        length = struct.unpack("!Q", data)[0]

    if length > max_payload:
        raise ValueError(f"Payload too large: {length} > {max_payload}")

    # Read masking key
    mask = await reader.readexactly(4)

    # Read and unmask payload
    if length > 0:
        payload = await reader.readexactly(length)
        payload = _apply_mask(payload, mask)
    else:
        payload = b""

    return Frame(fin=fin, opcode=opcode, payload=payload, rsv1=rsv1)


class HandshakeResult(NamedTuple):
    is_websocket: bool
    ws_key: str
    error: str
    permessage_deflate: bool = False


def validate_handshake_headers(
    headers: list[tuple[str, str]],
) -> HandshakeResult:
    """Validate WebSocket upgrade request headers.

    Returns HandshakeResult with is_websocket, ws_key, error, and
    whether the client requested permessage-deflate compression.
    """
    upgrade = ""
    connection = ""
    ws_key = ""
    ws_version = ""
    extensions = ""

    for name, value in headers:
        upper = name.upper() if isinstance(name, str) else name
        if upper == "UPGRADE":
            upgrade = value.lower()
        elif upper == "CONNECTION":
            connection = value.lower()
        elif upper == "SEC-WEBSOCKET-KEY":
            ws_key = value
        elif upper == "SEC-WEBSOCKET-VERSION":
            ws_version = value
        elif upper == "SEC-WEBSOCKET-EXTENSIONS":
            extensions = value

    if "upgrade" not in connection or upgrade != "websocket":
        return HandshakeResult(False, "", "")

    if ws_version != "13":
        return HandshakeResult(True, "", f"Unsupported WebSocket version: {ws_version}")

    if not ws_key:
        return HandshakeResult(True, "", "Missing Sec-WebSocket-Key")

    # Validate key is valid base64 (should decode to 16 bytes)
    try:
        decoded = base64.b64decode(ws_key, validate=True)
        if len(decoded) != 16:
            return HandshakeResult(True, "", "Invalid Sec-WebSocket-Key length")
    except Exception:
        return HandshakeResult(True, "", "Invalid Sec-WebSocket-Key encoding")

    # Check if client offers permessage-deflate
    has_deflate = "permessage-deflate" in extensions.lower()

    return HandshakeResult(True, ws_key, "", permessage_deflate=has_deflate)


def build_accept_response(ws_key: str, permessage_deflate: bool = False) -> bytes:
    """Build the HTTP 101 Switching Protocols response."""
    accept = compute_accept_key(ws_key)
    lines = [
        "HTTP/1.1 101 Switching Protocols",
        "Upgrade: websocket",
        "Connection: Upgrade",
        f"Sec-WebSocket-Accept: {accept}",
    ]
    if permessage_deflate:
        # server_no_context_takeover: fresh compressor per message (simpler,
        # uses slightly more bandwidth but avoids memory accumulation).
        lines.append(
            "Sec-WebSocket-Extensions: permessage-deflate; server_no_context_takeover; client_no_context_takeover"
        )
    lines.extend(["", ""])
    return "\r\n".join(lines).encode("utf-8")


async def read_messages(
    reader: asyncio.StreamReader,
    writer: Any,
    *,
    is_closed: Any,
    close: Any,
    on_pong: Any = None,
    max_message_size: int = MAX_DATA_PAYLOAD,
    permessage_deflate: bool = False,
) -> AsyncIterator[str | bytes]:
    """Read WebSocket messages from the stream.

    Handles framing, ping/pong, fragmentation reassembly, and close
    handshake. Yields decoded messages (str for text, bytes for binary).
    Stops iteration on close frame, connection error, or protocol error.

    Args:
        reader: Stream to read frames from.
        writer: Stream to write pong responses to (must have write/drain).
        is_closed: Callable returning True if the connection is closed.
        close: Async callable ``close(code, reason)`` to initiate close.
        on_pong: Optional callable invoked when a pong frame arrives.
        max_message_size: Maximum reassembled message size in bytes.
        permessage_deflate: Whether compression was negotiated.
    """
    frag_opcode = None
    frag_payload = bytearray()
    frag_compressed = False

    while not is_closed():
        try:
            frame = await read_frame(
                reader,
                max_payload=max_message_size,
                permessage_deflate=permessage_deflate,
            )
        except (asyncio.IncompleteReadError, ConnectionError):
            return
        except ValueError as e:
            if "too large" in str(e).lower():
                await close(CLOSE_MESSAGE_TOO_BIG, str(e))
            else:
                await close(CLOSE_PROTOCOL_ERROR, str(e))
            return

        if frame.opcode == OP_CLOSE:
            close_reason = parse_close_payload(frame.payload)
            # 1005 (no status) is reserved and must not be sent on the
            # wire — reply with a normal 1000 close instead.
            reply_code = (
                CLOSE_NORMAL
                if close_reason.code == CLOSE_NO_STATUS
                else close_reason.code
            )
            await close(reply_code)
            return

        if frame.opcode == OP_PING:
            writer.write(encode_frame(OP_PONG, frame.payload))
            await writer.drain()
            continue

        if frame.opcode == OP_PONG:
            if on_pong is not None:
                on_pong()
            continue

        # Data frames
        if frame.opcode == OP_CONTINUATION:
            if frag_opcode is None:
                await close(CLOSE_PROTOCOL_ERROR, "Unexpected continuation")
                return
            if frame.rsv1:
                await close(CLOSE_PROTOCOL_ERROR, "RSV1 on continuation frame")
                return
            frag_payload.extend(frame.payload)
            if len(frag_payload) > max_message_size:
                await close(CLOSE_MESSAGE_TOO_BIG, "Message too large")
                return
            if frame.fin:
                payload = bytes(frag_payload)
                if frag_compressed:
                    try:
                        payload = _decompress(payload)
                    except zlib.error:
                        await close(CLOSE_PROTOCOL_ERROR, "Decompression failed")
                        return
                    if len(payload) > max_message_size:
                        await close(CLOSE_MESSAGE_TOO_BIG, "Message too large")
                        return
                msg = _decode_payload(frag_opcode, payload)
                if msg is None:
                    await close(CLOSE_INVALID_PAYLOAD, "Invalid UTF-8")
                    return
                yield msg
                frag_opcode = None
                frag_payload.clear()
                frag_compressed = False
        elif frame.opcode in (OP_TEXT, OP_BINARY):
            if frag_opcode is not None:
                await close(
                    CLOSE_PROTOCOL_ERROR,
                    "New data frame during fragmentation",
                )
                return
            if frame.fin:
                payload = frame.payload
                if frame.rsv1:
                    try:
                        payload = _decompress(payload)
                    except zlib.error:
                        await close(CLOSE_PROTOCOL_ERROR, "Decompression failed")
                        return
                    if len(payload) > max_message_size:
                        await close(CLOSE_MESSAGE_TOO_BIG, "Message too large")
                        return
                msg = _decode_payload(frame.opcode, payload)
                if msg is None:
                    await close(CLOSE_INVALID_PAYLOAD, "Invalid UTF-8")
                    return
                yield msg
            else:
                frag_opcode = frame.opcode
                frag_compressed = frame.rsv1
                frag_payload.extend(frame.payload)
                if len(frag_payload) > max_message_size:
                    await close(CLOSE_MESSAGE_TOO_BIG, "Message too large")
                    return


# Trailing bytes appended before decompression / stripped after compression
# per RFC 7692 Section 7.2.2.
_DEFLATE_TAIL = b"\x00\x00\xff\xff"


def _compress(data: bytes) -> bytes:
    """Compress a message payload using raw deflate (RFC 7692)."""
    # Use raw deflate (wbits=-15), flush with Z_SYNC_FLUSH, strip tail
    compressor = zlib.compressobj(zlib.Z_DEFAULT_COMPRESSION, zlib.DEFLATED, -15)
    compressed = compressor.compress(data)
    compressed += compressor.flush(zlib.Z_SYNC_FLUSH)
    # Strip the trailing 0x00 0x00 0xff 0xff
    if compressed.endswith(_DEFLATE_TAIL):
        compressed = compressed[: -len(_DEFLATE_TAIL)]
    return compressed


def _decompress(data: bytes) -> bytes:
    """Decompress a message payload using raw deflate (RFC 7692)."""
    # Re-append the tail bytes and decompress with raw inflate.
    # Must use decompressobj — one-shot decompress() rejects the
    # truncated stream even after re-appending the sync marker.
    d = zlib.decompressobj(-15)
    return d.decompress(data + _DEFLATE_TAIL)


def _decode_payload(opcode: int, payload: bytes) -> str | bytes | None:
    """Decode a complete message payload based on opcode.

    Returns None on invalid UTF-8 for text frames.
    """
    if opcode == OP_TEXT:
        try:
            return payload.decode("utf-8")
        except UnicodeDecodeError:
            return None
    return payload
