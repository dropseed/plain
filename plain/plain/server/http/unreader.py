from __future__ import annotations

#
#
# This file is part of gunicorn released under the MIT license.
# See the LICENSE for more information.
#
# Vendored and modified for Plain.
import io
import os
import socket
from collections.abc import Iterable, Iterator
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

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
