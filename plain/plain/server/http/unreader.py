from __future__ import annotations

#
#
# This file is part of gunicorn released under the MIT license.
# See the LICENSE for more information.
#
# Vendored and modified for Plain.
import asyncio
import io
import os
import socket
from collections.abc import Iterable, Iterator
from typing import Any

from .. import util

# Classes that can undo reading data from
# a given type of data source.


class Unreader:
    def __init__(self):
        self.buf = io.BytesIO()

    def chunk(self) -> bytes:
        raise NotImplementedError()

    def read(self, size: int | None = None) -> bytes:
        if size is not None and not isinstance(size, int):
            raise TypeError("size parameter must be an int or long.")

        if size is not None:
            if size == 0:
                return b""
            if size < 0:
                size = None

        self.buf.seek(0, os.SEEK_END)

        if size is None and self.buf.tell():
            ret = self.buf.getvalue()
            self.buf = io.BytesIO()
            return ret
        if size is None:
            d = self.chunk()
            return d

        while self.buf.tell() < size:
            chunk = self.chunk()
            if not chunk:
                ret = self.buf.getvalue()
                self.buf = io.BytesIO()
                return ret
            self.buf.write(chunk)
        data = self.buf.getvalue()
        self.buf = io.BytesIO()
        self.buf.write(data[size:])
        return data[:size]

    def unread(self, data: bytes) -> None:
        self.buf.seek(0, os.SEEK_END)
        self.buf.write(data)


class SocketUnreader(Unreader):
    def __init__(self, sock: socket.socket, max_chunk: int = 8192):
        super().__init__()
        self.sock = sock
        self.mxchunk = max_chunk

    def chunk(self) -> bytes:
        return self.sock.recv(self.mxchunk)


class IterUnreader(Unreader):
    def __init__(self, iterable: Iterable[bytes]):
        super().__init__()
        self.iter: Iterator[bytes] | None = iter(iterable)

    def chunk(self) -> bytes:
        if not self.iter:
            return b""
        try:
            return next(self.iter)
        except StopIteration:
            self.iter = None
            return b""


class BufferUnreader(Unreader):
    """Unreader backed by pre-read bytes with no socket I/O.

    Used when headers and body have been read asynchronously on the
    event loop and the data is already in memory.  The parser reads
    headers from the buffer and sets up body readers (ChunkedReader,
    LengthReader) that also read from this buffer.
    """

    def __init__(self, data: bytes) -> None:
        super().__init__()
        self.buf.write(data)

    def chunk(self) -> bytes:
        # All data is pre-buffered; nothing more to read.
        return b""


class AsyncBridgeUnreader(Unreader):
    """Unreader that bridges async reads to sync parser reads.

    Used for large request bodies that shouldn't be fully pre-buffered.
    Headers and any initial body bytes are in the buffer. When the buffer
    is exhausted, chunk() bridges to the event loop via
    run_coroutine_threadsafe for lazy reads.

    Accepts either a TConn (which may have a StreamReader for TLS) or
    falls back to raw socket reads via util.async_recv.

    IMPORTANT: chunk() blocks the calling thread, so this unreader must
    only be used from a thread pool — never from the event loop thread.
    """

    def __init__(
        self,
        data: bytes,
        conn: Any,
        loop: asyncio.AbstractEventLoop,
        timeout: float = 30,
    ) -> None:
        super().__init__()
        self.buf.write(data)
        self._conn = conn
        self._loop = loop
        self._timeout = timeout
        self._eof = False
        self.socket_bytes_read = 0

    async def _async_read(self) -> bytes:
        """Read from the connection using streams or raw socket."""
        conn = self._conn
        if hasattr(conn, "reader") and conn.reader is not None:
            return await conn.reader.read(8192)
        sock = conn.sock if hasattr(conn, "sock") else conn
        return await util.async_recv(sock, 8192)

    def chunk(self) -> bytes:
        if self._eof:
            return b""
        future = asyncio.run_coroutine_threadsafe(self._async_read(), self._loop)
        try:
            # On Python 3.11+, concurrent.futures.TimeoutError is
            # builtins.TimeoutError so this except clause catches it.
            data = future.result(timeout=self._timeout)
        except TimeoutError:
            future.cancel()
            self._eof = True
            raise
        if not data:
            self._eof = True
        else:
            self.socket_bytes_read += len(data)
        return data
