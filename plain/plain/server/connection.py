from __future__ import annotations

import asyncio
import socket
import ssl
from typing import TYPE_CHECKING

from . import util

if TYPE_CHECKING:
    from .app import ServerApplication

# Keep-alive connection timeout in seconds
KEEPALIVE = 2


class Connection:
    def __init__(
        self,
        app: ServerApplication,
        sock: socket.socket,
        client: tuple[str, int],
        server: tuple[str, int],
    ) -> None:
        self.app = app
        self.sock = sock
        self.client = client
        self.server = server

        self.is_h2: bool = False
        self.is_ssl: bool = False
        self.handed_off: bool = False
        self.req_count: int = 0

        # Asyncio streams — set after TLS handshake via asyncio transport
        self.reader: asyncio.StreamReader | None = None
        self.writer: asyncio.StreamWriter | None = None

        # Byte read during keepalive wait, prepended to next header read
        self._keepalive_byte: bytes = b""

        # set the socket to non blocking
        self.sock.setblocking(False)

    def close(self) -> None:
        if self.writer is not None:
            if not self.writer.is_closing():
                self.writer.close()
        else:
            util.close(self.sock)

    async def recv(self, n: int) -> bytes:
        """Read up to n bytes from a connection.

        Uses StreamReader when available (TLS connections), otherwise
        falls back to the raw socket via util.async_recv().
        """
        if self.reader is not None:
            return await self.reader.read(n)
        return await util.async_recv(self.sock, n)

    async def sendall(self, data: bytes) -> None:
        """Send all bytes on a connection.

        Uses StreamWriter when available (TLS connections), otherwise
        falls back to the raw socket via util.async_sendall().
        """
        if self.writer is not None:
            self.writer.write(data)
            await self.writer.drain()
            return
        await util.async_sendall(self.sock, data)

    async def write_error(self, status_int: int, reason: str, mesg: str) -> None:
        """Send an HTTP error response on a connection."""
        await self.sendall(util._error_response_bytes(status_int, reason, mesg))

    async def wait_readable(self) -> None:
        # For asyncio stream connections, use a 1-byte read to wait for
        # data, then prepend it to the reader's buffer so it's not lost.
        if self.reader is not None:
            data = await self.reader.read(1)
            if data:
                # Prepend the peeked byte back into the buffer
                self._keepalive_byte = data
            return

        s = self.sock

        # SSL sockets may have decrypted data buffered internally that
        # won't trigger fd readability — check before waiting.
        if isinstance(s, ssl.SSLSocket) and s.pending() > 0:
            return

        loop = asyncio.get_running_loop()
        fut: asyncio.Future[None] = loop.create_future()

        def _on_readable() -> None:
            if not fut.done():
                loop.remove_reader(s)
                fut.set_result(None)

        try:
            loop.add_reader(s, _on_readable)
        except OSError:
            # Socket already closed by client
            return
        try:
            await fut
        except asyncio.CancelledError:
            loop.remove_reader(s)
            raise
