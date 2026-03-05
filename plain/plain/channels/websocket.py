"""WebSocket frame protocol implementation (RFC 6455).

Handles frame parsing, serialization, masking, the opening handshake,
and the close handshake. Used internally by WebSocketConnection.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import struct
from typing import NamedTuple

# WebSocket opcodes (RFC 6455 Section 5.2)
OP_CONTINUATION = 0x0
OP_TEXT = 0x1
OP_BINARY = 0x2
OP_CLOSE = 0x8
OP_PING = 0x9
OP_PONG = 0xA

# Magic GUID for Sec-WebSocket-Accept (RFC 6455 Section 4.2.2)
_WS_GUID = "258EAFA5-E914-47DA-95CA-5AB9DC085B11"

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


class CloseReason(NamedTuple):
    code: int
    reason: str


def compute_accept_key(key: str) -> str:
    """Compute the Sec-WebSocket-Accept value for the opening handshake."""
    digest = hashlib.sha1((key + _WS_GUID).encode()).digest()
    return base64.b64encode(digest).decode()


def _apply_mask(data: bytes, mask: bytes) -> bytes:
    """Apply XOR masking to data (RFC 6455 Section 5.3)."""
    if len(mask) != 4:
        raise ValueError("Mask must be 4 bytes")
    # Use int.from_bytes for fast XOR on 4-byte aligned chunks
    result = bytearray(data)
    for i in range(len(result)):
        result[i] ^= mask[i % 4]
    return bytes(result)


def encode_frame(
    opcode: int,
    payload: bytes = b"",
    fin: bool = True,
) -> bytes:
    """Encode a WebSocket frame for sending (server→client, no masking)."""
    header = bytearray()

    # First byte: FIN + opcode
    first_byte = (0x80 if fin else 0x00) | (opcode & 0x0F)
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
    """Parse a close frame payload into (code, reason)."""
    if len(payload) == 0:
        return CloseReason(CLOSE_NO_STATUS, "")
    if len(payload) == 1:
        # Invalid: close payload must be 0 or >= 2 bytes
        return CloseReason(CLOSE_PROTOCOL_ERROR, "")
    code = struct.unpack("!H", payload[:2])[0]
    reason = payload[2:].decode("utf-8", errors="replace")
    return CloseReason(code, reason)


async def read_frame(
    reader: asyncio.StreamReader,
    max_payload: int = MAX_DATA_PAYLOAD,
) -> Frame:
    """Read and decode a single WebSocket frame from the stream.

    Client→server frames must be masked (RFC 6455 Section 5.1).
    Raises ConnectionError on EOF, ValueError on protocol violations.
    """
    # Read first 2 bytes
    data = await reader.readexactly(2)
    first_byte, second_byte = data[0], data[1]

    fin = bool(first_byte & 0x80)
    rsv = (first_byte >> 4) & 0x07
    opcode = first_byte & 0x0F
    masked = bool(second_byte & 0x80)
    length = second_byte & 0x7F

    # RSV bits must be 0 (no extensions)
    if rsv != 0:
        raise ValueError(f"Non-zero RSV bits: {rsv:#x}")

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
            raise ValueError(f"Control frame payload too large: {length}")

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

    return Frame(fin=fin, opcode=opcode, payload=payload)


def validate_handshake_headers(
    headers: list[tuple[str, str]],
) -> tuple[bool, str, str]:
    """Validate WebSocket upgrade request headers.

    Returns (is_websocket, ws_key, error_reason).
    """
    upgrade = ""
    connection = ""
    ws_key = ""
    ws_version = ""

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

    if "upgrade" not in connection or upgrade != "websocket":
        return False, "", ""

    if ws_version != "13":
        return True, "", f"Unsupported WebSocket version: {ws_version}"

    if not ws_key:
        return True, "", "Missing Sec-WebSocket-Key"

    # Validate key is valid base64 (should decode to 16 bytes)
    try:
        decoded = base64.b64decode(ws_key)
        if len(decoded) != 16:
            return True, "", "Invalid Sec-WebSocket-Key length"
    except Exception:
        return True, "", "Invalid Sec-WebSocket-Key encoding"

    return True, ws_key, ""


def build_accept_response(ws_key: str) -> bytes:
    """Build the HTTP 101 Switching Protocols response."""
    accept = compute_accept_key(ws_key)
    lines = [
        "HTTP/1.1 101 Switching Protocols",
        "Upgrade: websocket",
        "Connection: Upgrade",
        f"Sec-WebSocket-Accept: {accept}",
        "",
        "",
    ]
    return "\r\n".join(lines).encode("utf-8")
