from __future__ import annotations

#
#
# This file is part of gunicorn released under the MIT license.
# See the LICENSE for more information.
#
# Vendored and modified for Plain.
import asyncio
import time
from collections import deque
from typing import Any

from ..connection import DRAIN_MIN_RECV

# Classes that can undo reading data from
# a given type of data source.


class Unreader:
    def __init__(self):
        # Buffered-but-unconsumed chunks, consumed from the front.
        # _offset is the already-consumed prefix of _chunks[0]: advancing
        # it instead of re-slicing the front chunk keeps read(size) O(size)
        # even when the buffer holds an entire pre-buffered body — slicing
        # would copy the remainder on every read, which is quadratic
        # (multi-second stalls on multi-MB bodies).
        self._chunks: deque[bytes] = deque()
        self._offset = 0
        self._buffered = 0

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

        if size is None:
            if self._buffered:
                return self._take(self._buffered)
            return self.chunk()

        while self._buffered < size:
            data = self.chunk()
            if not data:
                # EOF before size bytes arrived — return what's buffered.
                return self._take(self._buffered)
            self._chunks.append(data)
            self._buffered += len(data)

        return self._take(size)

    def read_some(self, max_size: int) -> bytes:
        """Return up to max_size buffered bytes, or one chunk()'s worth.

        Unlike read(size), this never waits for more than one chunk() —
        a streaming body keeps flowing at whatever pace bytes arrive.
        Bounding the piece size keeps the chunked parser's slicing O(1)
        per piece when the buffer holds an entire pre-buffered body.
        Returns b"" only at EOF.
        """
        if max_size <= 0:
            # A non-positive cap would buffer a chunk() and return b"",
            # which callers would misread as EOF.
            raise ValueError("max_size must be positive.")
        if not self._buffered:
            data = self.chunk()
            if not data:
                return b""
            self._chunks.append(data)
            self._buffered += len(data)
        return self._take(min(max_size, self._buffered))

    def _take(self, size: int) -> bytes:
        """Remove and return exactly size bytes from the buffer (size <= _buffered)."""
        pieces = []
        need = size
        while need:
            front = self._chunks[0]
            available = len(front) - self._offset
            if available <= need:
                pieces.append(front[self._offset :] if self._offset else front)
                self._chunks.popleft()
                self._offset = 0
                self._buffered -= available
                need -= available
            else:
                pieces.append(front[self._offset : self._offset + need])
                self._offset += need
                self._buffered -= need
                need = 0
        return b"".join(pieces)

    def unread(self, data: bytes) -> None:
        # Pushed back at the FRONT: an unread byte is the next byte read.
        # Callers may unread while data is still buffered (the chunked
        # parser over-reads via read_some and puts the tail back), so
        # appending at the end would reorder the stream.
        if data:
            if self._offset:
                self._chunks[0] = self._chunks[0][self._offset :]
                self._offset = 0
            self._chunks.appendleft(data)
            self._buffered += len(data)


class BufferUnreader(Unreader):
    """Unreader backed by pre-read bytes with no socket I/O.

    Used when headers and body have been read asynchronously on the
    event loop and the data is already in memory.  The parser reads
    headers from the buffer and sets up body readers (ChunkedReader,
    LengthReader) that also read from this buffer.
    """

    def __init__(self, data: bytes) -> None:
        super().__init__()
        self.unread(data)

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
        self.unread(data)
        self._conn = conn
        self._loop = loop
        self._timeout = timeout
        # Worker whose drain_read_deadline caps reads during shutdown.
        # Read live on each chunk so a SIGTERM mid-body applies too.
        self._worker = worker
        self._eof = False
        self.socket_bytes_read = 0

    async def _async_read(self) -> bytes:
        """Read the next bytes from the connection.

        Goes through Connection.recv (never conn.reader directly) so
        bytes peeked by wait_readable are drained, not skipped.
        """
        return await self._conn.recv(8192)

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
