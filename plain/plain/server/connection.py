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
        # _peek_offset is the consumed prefix: advancing it instead of
        # re-slicing keeps draining a large peek in small reads O(n).
        self._peeked: bytes = b""
        self._peek_offset = 0

        # True while the current request is a HEAD — latched from the
        # request line the moment its header bytes are read, before any
        # parsing, so even an error response to an unparseable request
        # is bodiless for HEAD (RFC 9110 9.3.2). Reset per request by
        # the h1 connection loop; False when the request line was never
        # read (e.g. oversized headers).
        self.request_is_head: bool = False

    def close(self) -> None:
        if not self.writer.is_closing():
            self.writer.close()

    async def recv(self, n: int) -> bytes:
        """Read up to n bytes from a connection."""
        if self._peeked:
            available = len(self._peeked) - self._peek_offset
            if available <= n:
                data = (
                    self._peeked[self._peek_offset :]
                    if self._peek_offset
                    else self._peeked
                )
                self._peeked = b""
                self._peek_offset = 0
            else:
                data = self._peeked[self._peek_offset : self._peek_offset + n]
                self._peek_offset += n
            return data
        return await self.reader.read(n)

    async def sendall(self, data: bytes) -> None:
        """Send all bytes on a connection."""
        self.writer.write(data)
        await self.writer.drain()

    async def write_error(self, status_int: int, reason: str, mesg: str) -> None:
        """Send an HTTP error response on a connection.

        Headers-only when the current request is a HEAD.
        """
        await self.sendall(
            util._error_response_bytes(
                status_int, reason, mesg, head=self.request_is_head
            )
        )

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
            self._peeked = data
            self._peek_offset = 0
            return True
        return False
