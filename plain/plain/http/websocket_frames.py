"""RFC 6455 WebSocket frame codec.

Frames in, frames out — nothing else. This module knows how a single frame is
laid out on the wire, how masking works, what a close payload means, and how
the two handshake values (`Sec-WebSocket-Accept`, `Sec-WebSocket-Protocol`) are
computed. It does not assemble messages from fragments, validate an upgrade
request, speak the close handshake, or negotiate extensions — those live in
`plain.http.websocket`.

No compression. Plain never advertises permessage-deflate, so RSV1 (like RSV2
and RSV3) is always a protocol error here.

Stdlib only, and no imports from anywhere else in Plain.
"""

from __future__ import annotations

import base64
import hashlib
import struct
import sys
from collections.abc import Awaitable, Callable
from typing import NamedTuple

# Opcodes (RFC 6455 Section 5.2)
OP_CONTINUATION = 0x0
OP_TEXT = 0x1
OP_BINARY = 0x2
OP_CLOSE = 0x8
OP_PING = 0x9
OP_PONG = 0xA

_OPCODES = frozenset({OP_CONTINUATION, OP_TEXT, OP_BINARY, OP_CLOSE, OP_PING, OP_PONG})

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

# Control frames carry at most 125 bytes and are never fragmented
# (RFC 6455 Section 5.5).
MAX_CONTROL_PAYLOAD = 125

# Magic GUID for Sec-WebSocket-Accept (RFC 6455 Section 4.2.2)
_WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


class ProtocolError(Exception):
    """The peer sent something RFC 6455 forbids. The socket closes with 1002."""


class PayloadTooLarge(Exception):
    """A frame or message larger than the caller's cap; the socket closes with 1009.

    `read_frame` raises it from the header, before a single payload byte is
    read, so a declared 4 GiB frame costs nothing. The message layer raises
    it again when reassembled fragments pass the cap.
    """

    def __init__(self, length: int, max_payload: int) -> None:
        super().__init__(f"Payload too large: {length} > {max_payload}")
        self.length = length
        self.max_payload = max_payload


class IncompleteFrame(Exception):
    """The peer stopped sending. Not a protocol error — the caller decides.

    Raised both when the stream ends cleanly on a frame boundary and when it
    ends partway through a frame, because `read_frame` only ever asks for bytes
    it needs. A reader that was waiting for the next frame treats this as the
    connection ending; anything else is an abnormal close.
    """


class Frame(NamedTuple):
    fin: bool
    opcode: int
    payload: bytes


class CloseReason(NamedTuple):
    code: int
    reason: str


def compute_accept_key(key: str) -> str:
    """Compute the `Sec-WebSocket-Accept` value for a request's key."""
    digest = hashlib.sha1((key + _WS_GUID).encode()).digest()
    return base64.b64encode(digest).decode()


def apply_mask(data: bytes, mask: bytes) -> bytes:
    """XOR `data` with the repeating 4-byte `mask` (RFC 6455 Section 5.3).

    Masking is its own inverse, so this both masks and unmasks. The whole
    payload is XORed as one big integer: faster than any Python-level loop
    at every size, at the cost of transient integers a few times the
    payload's size while it runs.
    """
    if len(mask) != 4:
        raise ValueError("Mask must be 4 bytes")
    n = len(data)
    if n == 0:
        return b""
    repeated_mask = mask * (n // 4) + mask[: n % 4]
    data_int = int.from_bytes(data, sys.byteorder)
    mask_int = int.from_bytes(repeated_mask, sys.byteorder)
    return (data_int ^ mask_int).to_bytes(n, sys.byteorder)


def encode_frame(
    opcode: int, payload: bytes = b"", fin: bool = True, *, mask: bytes | None = None
) -> bytes:
    """Encode one frame.

    Server-to-client frames are never masked (the default). A client —
    the test client, or a test speaking to the server — passes a 4-byte
    `mask`, which sets the mask bit and masks the payload.
    """
    header = bytearray()

    # First byte: FIN, three zero reserved bits, opcode.
    header.append((0x80 if fin else 0x00) | (opcode & 0x0F))

    # Second byte: the mask bit and the length, which spills into 2 or 8
    # extra bytes once it no longer fits in 7 bits.
    mask_bit = 0x80 if mask is not None else 0x00
    length = len(payload)
    if length < 126:
        header.append(mask_bit | length)
    elif length < 65536:
        header.append(mask_bit | 126)
        header.extend(struct.pack("!H", length))
    else:
        header.append(mask_bit | 127)
        header.extend(struct.pack("!Q", length))

    if mask is None:
        return bytes(header) + payload
    return bytes(header) + mask + apply_mask(payload, mask)


def encode_close(
    code: int = CLOSE_NORMAL, reason: str = "", *, mask: bytes | None = None
) -> bytes:
    """Encode a complete CLOSE frame carrying `code` and `reason`."""
    payload = struct.pack("!H", code) + reason.encode("utf-8")
    return encode_frame(OP_CLOSE, payload, mask=mask)


def is_valid_close_code(code: int) -> bool:
    """Is `code` a close code a peer is allowed to put on the wire?

    1004, 1005, 1006 and 1015 are reserved for local use and never sent
    (RFC 6455 Section 7.4.1).
    """
    if 1000 <= code <= 1003:
        return True
    if 1007 <= code <= 1014:  # 1012-1014 are IANA-registered
        return True
    if 3000 <= code <= 3999:  # libraries and frameworks
        return True
    # 4000-4999 is private use. Everything left over (0-999, 1004-1006,
    # 1015-2999, 5000 and up) is reserved or out of range.
    return 4000 <= code <= 4999


def parse_close_payload(payload: bytes) -> CloseReason:
    """Parse a CLOSE frame's payload.

    An empty payload means "no status given" — 1005, which is a local code and
    must never be echoed back onto the wire. Anything malformed is a protocol
    error: a lone byte, a reserved or out-of-range code, or a reason that is
    not valid UTF-8.
    """
    if len(payload) == 0:
        return CloseReason(CLOSE_NO_STATUS, "")
    if len(payload) == 1:
        raise ProtocolError("Close payload must be empty or at least 2 bytes")
    code = int.from_bytes(payload[:2], "big")
    if not is_valid_close_code(code):
        raise ProtocolError(f"Invalid close code: {code}")
    try:
        reason = payload[2:].decode("utf-8")
    except UnicodeDecodeError:
        raise ProtocolError("Invalid UTF-8 in close reason") from None
    return CloseReason(code, reason)


async def _read_exactly(recv: Callable[[int], Awaitable[bytes]], n: int) -> bytes:
    """Read exactly `n` bytes, looping over however many short reads it takes."""
    if n == 0:
        return b""
    chunk = await recv(n)
    if len(chunk) == n:
        return chunk
    if not chunk:
        raise IncompleteFrame(f"Stream ended, wanted {n} more bytes")
    parts = [chunk]
    remaining = n - len(chunk)
    while remaining > 0:
        chunk = await recv(remaining)
        if not chunk:
            raise IncompleteFrame(f"Stream ended, wanted {remaining} more bytes")
        parts.append(chunk)
        remaining -= len(chunk)
    return b"".join(parts)


async def read_frame(
    recv: Callable[[int], Awaitable[bytes]],
    max_payload: int,
    *,
    require_mask: bool = True,
) -> Frame:
    """Read one frame, payload already unmasked.

    `recv(n)` returns up to `n` bytes, or `b""` at end of stream; short reads
    are normal and are looped over. The stream ending raises `IncompleteFrame`,
    a violation raises `ProtocolError`, and a declared length above
    `max_payload` raises `PayloadTooLarge` from the header alone.

    The server reads client frames, which must be masked (the default). A
    client reading server frames passes `require_mask=False`; a masked
    frame is still unmasked correctly either way.
    """
    header = await _read_exactly(recv, 2)
    first_byte, second_byte = header[0], header[1]

    fin = bool(first_byte & 0x80)
    opcode = first_byte & 0x0F
    masked = bool(second_byte & 0x80)
    length = second_byte & 0x7F

    # No extension is ever negotiated, so all three reserved bits must be zero.
    if first_byte & 0x70:
        raise ProtocolError("Non-zero RSV bits")

    if opcode not in _OPCODES:
        raise ProtocolError(f"Unknown opcode: {opcode:#x}")

    # Every client-to-server frame is masked (RFC 6455 Section 5.1).
    if require_mask and not masked:
        raise ProtocolError("Client frame is not masked")

    if opcode >= OP_CLOSE:
        if not fin:
            raise ProtocolError("Fragmented control frame")
        if length > MAX_CONTROL_PAYLOAD:
            raise ProtocolError(f"Control frame payload too long: {length}")

    if length == 126:
        length = int.from_bytes(await _read_exactly(recv, 2), "big")
    elif length == 127:
        length = int.from_bytes(await _read_exactly(recv, 8), "big")
        # The most significant bit of a 64-bit length must be 0
        # (RFC 6455 Section 5.2).
        if length & (1 << 63):
            raise ProtocolError("64-bit payload length has the high bit set")

    # Checked before the payload is touched: a frame that claims gigabytes
    # must not cost gigabytes to reject. Control frames are bounded by the
    # protocol's own 125 bytes above, not by the application's cap.
    if opcode < OP_CLOSE and length > max_payload:
        raise PayloadTooLarge(length, max_payload)

    if masked:
        mask = await _read_exactly(recv, 4)
        payload = apply_mask(await _read_exactly(recv, length), mask)
    else:
        payload = await _read_exactly(recv, length)

    return Frame(fin=fin, opcode=opcode, payload=payload)
