from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from . import util

if TYPE_CHECKING:
    from .app import ServerApplication

# Keep-alive connection timeout in seconds
KEEPALIVE = 2

# Per-recv timeout floor during shutdown drain. The drain deadline caps
# total read time, but each individual recv still gets at least this long
# so a request whose bytes are already buffered (or arrive in one segment,
# as a router's pooled connection does) is always drained rather than
# dropped by a zero-length timeout.
DRAIN_MIN_RECV = 0.5


class Connection:
    def __init__(
        self,
        app: ServerApplication,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        client: tuple[str, int],
        server: tuple[str, int],
        *,
        is_ssl: bool = False,
    ) -> None:
        self.app = app
        self.reader = reader
        self.writer = writer
        self.client = client
        self.server = server

        self.is_h2: bool = False
        self.is_ssl: bool = is_ssl
        self.req_count: int = 0

        # Byte read during the keepalive wait, prepended to the next header
        # read so wait_readable()'s peek isn't lost.
        self._keepalive_byte: bytes = b""

    def close(self) -> None:
        if not self.writer.is_closing():
            self.writer.close()

    async def recv(self, n: int) -> bytes:
        """Read up to n bytes from a connection."""
        return await self.reader.read(n)

    async def sendall(self, data: bytes) -> None:
        """Send all bytes on a connection."""
        self.writer.write(data)
        await self.writer.drain()

    async def write_error(self, status_int: int, reason: str, mesg: str) -> None:
        """Send an HTTP error response on a connection."""
        await self.sendall(util._error_response_bytes(status_int, reason, mesg))

    async def wait_readable(self) -> None:
        """Return when the next request's bytes are available to recv."""
        data = await self.reader.read(1)
        if data:
            # Prepend the peeked byte back into the next read.
            self._keepalive_byte = data
