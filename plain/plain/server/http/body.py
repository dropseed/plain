from __future__ import annotations

#
#
# This file is part of gunicorn released under the MIT license.
# See the LICENSE for more information.
#
# Vendored and modified for Plain.
import io
import sys
from collections.abc import Generator, Iterator
from typing import TYPE_CHECKING

from plain.http import BadRequestError400

from .errors import (
    ChunkMissingTerminator,
    InvalidChunkSize,
    NoMoreData,
)

if TYPE_CHECKING:
    from .message import Message
    from .unreader import Unreader

# Ceiling per read while parsing a chunked body. The parser slices and
# re-buffers the piece it's working on, so an unbounded read — which
# returns an entire pre-buffered body at once — would make each of those
# copies O(body) and the whole parse quadratic. read_some() never waits
# to accumulate this much; it just caps what one call can return.
CHUNK_PARSE_MAX_READ = 64 * 1024

# Ceiling on the chunk-size line (hex size + optional extensions). A
# legitimate line is tens of bytes; without a cap, a client trickling
# bytes that never contain \r\n grows parse_chunk_size's buffer without
# bound while it re-scans from the start — quadratic CPU and unbounded
# memory on a single pre-auth request.
CHUNK_SIZE_LINE_MAX = 8192


class ChunkedReader:
    def __init__(self, req: Message, unreader: Unreader) -> None:
        self.req = req
        self.parser: Generator[bytes] | None = self.parse_chunked(unreader)
        self.buf = io.BytesIO()

    def read(self, size: int) -> bytes:
        if not isinstance(size, int):
            raise TypeError("size must be an integer type")
        if size < 0:
            raise ValueError("Size must be positive.")
        if size == 0:
            return b""

        if self.parser:
            while self.buf.tell() < size:
                try:
                    self.buf.write(next(self.parser))
                except StopIteration:
                    self.parser = None
                    break

        data = self.buf.getvalue()
        ret, rest = data[:size], data[size:]
        self.buf = io.BytesIO()
        self.buf.write(rest)
        return ret

    def parse_trailers(self, unreader: Unreader, data: bytes) -> None:
        buf = io.BytesIO()
        buf.write(data)

        idx = buf.getvalue().find(b"\r\n\r\n")
        done = buf.getvalue()[:2] == b"\r\n"
        while idx < 0 and not done:
            # HTTPException, not a ParseException: the body is parsed
            # lazily as the app reads, so this raises mid-dispatch where
            # a ParseException (an IOError) would be misread as a socket
            # error and the client would get no response at all.
            if buf.tell() > self.req.max_buffer_headers:
                raise BadRequestError400("Chunked trailer section too large")
            self.get_data(unreader, buf)
            idx = buf.getvalue().find(b"\r\n\r\n")
            done = buf.getvalue()[:2] == b"\r\n"
        if done:
            unreader.unread(buf.getvalue()[2:])
            return
        self.req.trailers = self.req.parse_headers(
            buf.getvalue()[:idx], from_trailer=True
        )
        unreader.unread(buf.getvalue()[idx + 4 :])
        return

    def parse_chunked(self, unreader: Unreader) -> Generator[bytes]:
        (size, rest) = self.parse_chunk_size(unreader)
        while size > 0:
            while size > len(rest):
                size -= len(rest)
                yield rest
                rest = unreader.read_some(CHUNK_PARSE_MAX_READ)
                if not rest:
                    raise NoMoreData()
            yield rest[:size]
            # Remove \r\n after chunk
            rest = rest[size:]
            while len(rest) < 2:
                new_data = unreader.read_some(CHUNK_PARSE_MAX_READ)
                if not new_data:
                    break
                rest += new_data
            if rest[:2] != b"\r\n":
                raise ChunkMissingTerminator(rest[:2])
            (size, rest) = self.parse_chunk_size(unreader, data=rest[2:])

    def parse_chunk_size(
        self, unreader: Unreader, data: bytes | None = None
    ) -> tuple[int, bytes]:
        buf = io.BytesIO()
        if data is not None:
            buf.write(data)

        idx = buf.getvalue().find(b"\r\n")
        while idx < 0:
            # HTTPException, not InvalidChunkSize — see parse_trailers.
            if buf.tell() > CHUNK_SIZE_LINE_MAX:
                raise BadRequestError400("Chunk size line too long")
            self.get_data(unreader, buf)
            idx = buf.getvalue().find(b"\r\n")
        if idx > CHUNK_SIZE_LINE_MAX:
            # The whole overlong line can arrive in one read — the loop
            # cap above never sees it.
            raise BadRequestError400("Chunk size line too long")

        data = buf.getvalue()
        line, rest_chunk = data[:idx], data[idx + 2 :]

        # RFC9112 7.1.1: BWS before chunk-ext - but ONLY then
        chunk_size, *chunk_ext = line.split(b";", 1)
        if chunk_ext:
            chunk_size = chunk_size.rstrip(b" \t")
        if any(n not in b"0123456789abcdefABCDEF" for n in chunk_size):
            raise InvalidChunkSize(chunk_size)
        if len(chunk_size) == 0:
            raise InvalidChunkSize(chunk_size)
        chunk_size = int(chunk_size, 16)

        if chunk_size == 0:
            try:
                self.parse_trailers(unreader, rest_chunk)
            except NoMoreData:
                pass
            return (0, b"")
        return (chunk_size, rest_chunk)

    def get_data(self, unreader: Unreader, buf: io.BytesIO) -> None:
        data = unreader.read_some(CHUNK_PARSE_MAX_READ)
        if not data:
            raise NoMoreData()
        buf.write(data)


class LengthReader:
    def __init__(self, unreader: Unreader, length: int) -> None:
        self.unreader = unreader
        self.length = length

    def read(self, size: int) -> bytes:
        if not isinstance(size, int):
            raise TypeError("size must be an integral type")

        size = min(self.length, size)
        if size < 0:
            raise ValueError("Size must be positive.")
        if size == 0:
            return b""

        # read_some, not read(size): return whatever has arrived (up to
        # size) instead of blocking until size bytes accumulate — on a
        # streaming body, readline() must get the short line the client
        # already sent, not wait for a full stride. Callers loop on short
        # reads. It also never drains-and-unreads the whole buffer, which
        # would be quadratic on large pre-buffered bodies.
        data = self.unreader.read_some(size)
        if not data:
            # EOF before the declared length arrived — the body is done;
            # length must reach 0 so this reader reads as finished.
            self.length = 0
        else:
            self.length -= len(data)
        return data


class Body:
    def __init__(self, reader: ChunkedReader | LengthReader) -> None:
        self.reader = reader
        self.buf = io.BytesIO()

    def __iter__(self) -> Iterator[bytes]:
        return self

    def __next__(self) -> bytes:
        ret = self.readline()
        if not ret:
            raise StopIteration()
        return ret

    next = __next__

    def getsize(self, size: int | None) -> int:
        if size is None:
            return sys.maxsize
        elif not isinstance(size, int):
            raise TypeError("size must be an integral type")
        elif size < 0:
            return sys.maxsize
        return size

    def read(self, size: int | None = None) -> bytes:
        size = self.getsize(size)
        if size == 0:
            return b""

        if size < self.buf.tell():
            data = self.buf.getvalue()
            ret, rest = data[:size], data[size:]
            self.buf = io.BytesIO()
            self.buf.write(rest)
            return ret

        while size > self.buf.tell():
            # Never ask for more than the caller still needs: on a
            # streaming (bridged) body, an oversized read would block
            # waiting for bytes the caller never requested.
            data = self.reader.read(min(CHUNK_PARSE_MAX_READ, size - self.buf.tell()))
            if not data:
                break
            self.buf.write(data)

        data = self.buf.getvalue()
        ret, rest = data[:size], data[size:]
        self.buf = io.BytesIO()
        self.buf.write(rest)
        return ret

    def readline(self, size: int | None = None) -> bytes:
        size = self.getsize(size)
        if size == 0:
            return b""

        data = self.buf.getvalue()
        self.buf = io.BytesIO()

        ret = []
        while 1:
            idx = data.find(b"\n", 0, size)
            idx = idx + 1 if idx >= 0 else size if len(data) >= size else 0
            if idx:
                ret.append(data[:idx])
                self.buf.write(data[idx:])
                break

            ret.append(data)
            size -= len(data)
            data = self.reader.read(min(1024, size))
            if not data:
                break

        return b"".join(ret)

    def close(self) -> None:
        pass

    def readlines(self, size: int | None = None) -> list[bytes]:
        ret = []
        data = self.read()
        while data:
            pos = data.find(b"\n")
            if pos < 0:
                ret.append(data)
                data = b""
            else:
                line, data = data[: pos + 1], data[pos + 1 :]
                ret.append(line)
        return ret
