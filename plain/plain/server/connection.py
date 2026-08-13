from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from . import util

if TYPE_CHECKING:
    from .app import ServerApplication

# Per-recv progress timeout (seconds) while actively reading a request's
# headers or body — slowloris protection, paired with HEADER_READ_TIMEOUT
# in h1. Unrelated to how long an idle keep-alive connection may sit
# between requests; that's SERVER_KEEPALIVE_TIMEOUT.
RECV_PROGRESS_TIMEOUT = 2

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

        # Bytes read by wait_readable()'s peek, handed back by the next
        # recv() calls so the peek is never lost — recv() drains this
        # before touching the reader, so callers don't need to know.
        self._peeked: bytes = b""

    def close(self) -> None:
        if not self.writer.is_closing():
            self.writer.close()

    async def recv(self, n: int) -> bytes:
        """Read up to n bytes from a connection."""
        if self._peeked:
            if len(self._peeked) <= n:
                data = self._peeked
                self._peeked = b""
            else:
                data = self._peeked[:n]
                self._peeked = self._peeked[n:]
            return data
        return await self.reader.read(n)

    async def sendall(self, data: bytes) -> None:
        """Send all bytes on a connection."""
        self.writer.write(data)
        await self.writer.drain()

    async def write_error(self, status_int: int, reason: str, mesg: str) -> None:
        """Send an HTTP error response on a connection."""
        await self.sendall(util._error_response_bytes(status_int, reason, mesg))

    async def wait_readable(self) -> bool:
        """Wait for the next request's bytes; True when bytes arrived.

        The peeked bytes are handed back by the next recv() calls.
        Returns False on EOF (the peer closed). Reads a full segment
        rather than one byte so a small request usually needs no second
        reader round trip.
        """
        if self._peeked:
            # Bytes from a previous peek are still buffered (e.g. a
            # pipelined request behind an exactly-consumed body) — they
            # ARE the next request; blocking on the socket would strand
            # them until the idle timeout.
            return True
        data = await self.reader.read(65536)
        if data:
            self._peeked += data
            return True
        return False
