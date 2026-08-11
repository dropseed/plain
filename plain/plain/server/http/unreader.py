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
import time
from typing import Any

from ..connection import DRAIN_MIN_RECV

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
    run_coroutine_threadsafe for lazy reads from the Connection's
    asyncio StreamReader.

    IMPORTANT: chunk() blocks the calling thread, so this unreader must
    only be used from a thread pool — never from the event loop thread.
    """

    def __init__(
        self,
        data: bytes,
        conn: Any,
        loop: asyncio.AbstractEventLoop,
        timeout: float = 30,
        worker: Any = None,
    ) -> None:
        super().__init__()
        self.buf.write(data)
        self._conn = conn
        self._loop = loop
        self._timeout = timeout
        # Worker whose drain_read_deadline caps reads during shutdown.
        # Read live on each chunk so a SIGTERM mid-body applies too.
        self._worker = worker
        self._eof = False
        self.socket_bytes_read = 0

    async def _async_read(self) -> bytes:
        """Read the next bytes from the connection's stream."""
        return await self._conn.reader.read(8192)

    def chunk(self) -> bytes:
        if self._eof:
            return b""
        timeout = self._timeout
        deadline = self._worker.drain_read_deadline if self._worker else None
        if deadline is not None:
            # Floor at DRAIN_MIN_RECV (like the pre-buffer paths) so a
            # large body already buffered in the StreamReader isn't dropped
            # by a zero-length wait right at the deadline.
            timeout = min(timeout, max(DRAIN_MIN_RECV, deadline - time.monotonic()))
        future = asyncio.run_coroutine_threadsafe(self._async_read(), self._loop)
        try:
            # On Python 3.11+, concurrent.futures.TimeoutError is
            # builtins.TimeoutError so this except clause catches it.
            data = future.result(timeout=timeout)
        except TimeoutError:
            # The read outlived its budget. Cancel it (if it hasn't
            # started) and give up — the connection is about to close, so
            # any bytes a running recv still collects are discarded with it.
            future.cancel()
            self._eof = True
            raise
        if not data:
            self._eof = True
        else:
            self.socket_bytes_read += len(data)
        return data
