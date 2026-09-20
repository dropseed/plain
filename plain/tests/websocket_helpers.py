"""Client-side WebSocket framing for tests that speak to the server directly."""

from __future__ import annotations

import asyncio

from plain.http.websocket_frames import (
    OP_CLOSE,
    OP_TEXT,
    Frame,
    encode_close,
    encode_frame,
    read_frame,
)
from plain.test.websocket import handshake_headers

# The RFC 6455 Section 1.3 example key and the accept it must produce.
UPGRADE_KEY = "dGhlIHNhbXBsZSBub25jZQ=="
UPGRADE_ACCEPT = "s3pPLMBiTxaQ9kYGzzhZRbK+xOo="

MASK = b"\x01\x02\x03\x04"


def upgrade_headers(
    *,
    protocols: str | None = None,
    extra: dict[str, str] | None = None,
) -> dict[str, str]:
    """A well-formed opening handshake using the RFC's example key."""
    headers = handshake_headers(key=UPGRADE_KEY)
    if protocols is not None:
        headers["Sec-WebSocket-Protocol"] = protocols
    if extra:
        headers.update(extra)
    return headers


def upgrade_request(
    path: str = "/websocket/echo",
    *,
    protocols: str | None = None,
    extra: dict[str, str] | None = None,
) -> bytes:
    """A raw HTTP/1.1 handshake request for the h1 connection loop."""
    lines = [f"GET {path} HTTP/1.1", "Host: testserver"]
    lines.extend(
        f"{name}: {value}"
        for name, value in upgrade_headers(protocols=protocols, extra=extra).items()
    )
    return ("\r\n".join(lines) + "\r\n\r\n").encode()


def client_frame(
    opcode: int = OP_TEXT, payload: bytes = b"", *, fin: bool = True
) -> bytes:
    """One masked client-to-server frame."""
    return encode_frame(opcode, payload, fin, mask=MASK)


def client_close(code: int = 1000, reason: str = "") -> bytes:
    return encode_close(code, reason, mask=MASK)


async def read_server_frame(
    reader: asyncio.StreamReader, *, timeout: float = 5.0
) -> Frame:
    """Read one unmasked server-to-client frame."""
    return await asyncio.wait_for(
        read_frame(reader.read, 16 * 1024 * 1024, require_mask=False), timeout
    )


def close_code(frame: Frame) -> int:
    assert frame.opcode == OP_CLOSE, f"expected CLOSE, got opcode {frame.opcode:#x}"
    return int.from_bytes(frame.payload[:2], "big")
