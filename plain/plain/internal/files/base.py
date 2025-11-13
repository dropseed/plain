from __future__ import annotations

import os
from functools import cached_property
from io import UnsupportedOperation
from typing import TYPE_CHECKING

from plain.internal.files.utils import FileProxyMixin

if TYPE_CHECKING:
    from collections.abc import Iterator
    from typing import IO, Any


class File(FileProxyMixin):
    DEFAULT_CHUNK_SIZE = 64 * 2**10

    def __init__(self, file: IO[Any], name: str | None = None) -> None:
        self.file = file
        if name is None:
            name = getattr(file, "name", None)
        self.name = name
        if hasattr(file, "mode"):
            self.mode = file.mode

    def __str__(self) -> str:
        return self.name or ""

    def __repr__(self) -> str:
        return "<{}: {}>".format(self.__class__.__name__, self or "None")

    def __bool__(self) -> bool:
        return bool(self.name)

    def __len__(self) -> int:
        return self.size

    @cached_property
    def size(self) -> int:
        if hasattr(self.file, "size"):
            return self.file.size  # type: ignore[return-value]
        if hasattr(self.file, "name"):
            try:
                return os.path.getsize(self.file.name)
            except (OSError, TypeError):
                pass
        if hasattr(self.file, "tell") and hasattr(self.file, "seek"):
            pos = self.file.tell()
            self.file.seek(0, os.SEEK_END)
            size = self.file.tell()
            self.file.seek(pos)
            return size
        raise AttributeError("Unable to determine the file's size.")

    def chunks(self, chunk_size: int | None = None) -> Iterator[bytes]:
        """
        Read the file and yield chunks of ``chunk_size`` bytes (defaults to
        ``File.DEFAULT_CHUNK_SIZE``).
        """
        chunk_size = chunk_size or self.DEFAULT_CHUNK_SIZE
        try:
            self.seek(0)
        except (AttributeError, UnsupportedOperation):
            pass

        while True:
            data = self.read(chunk_size)
            if not data:
                break
            yield data

    def multiple_chunks(self, chunk_size: int | None = None) -> bool:
        """
        Return ``True`` if you can expect multiple chunks.

        NB: If a particular file representation is in memory, subclasses should
        always return ``False`` -- there's no good reason to read from memory in
        chunks.
        """
        return self.size > (chunk_size or self.DEFAULT_CHUNK_SIZE)

    def __iter__(self) -> Iterator[bytes | str]:
        # Iterate over this file-like object by newlines
        buffer_ = None
        for chunk in self.chunks():
            for line in chunk.splitlines(True):
                if buffer_:
                    if endswith_cr(buffer_) and not equals_lf(line):
                        # Line split after a \r newline; yield buffer_.
                        yield buffer_
                        # Continue with line.
                    else:
                        # Line either split without a newline (line
                        # continues after buffer_) or with \r\n
                        # newline (line == b'\n').
                        line = buffer_ + line
                    # buffer_ handled, clear it.
                    buffer_ = None

                # If this is the end of a \n or \r\n line, yield.
                if endswith_lf(line):
                    yield line
                else:
                    buffer_ = line

        if buffer_ is not None:
            yield buffer_

    def __enter__(self) -> File:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        tb: Any,
    ) -> None:
        self.close()

    def open(self, mode: str | None = None) -> File:
        if not self.closed:
            self.seek(0)
        elif self.name and os.path.exists(self.name):
            self.file = open(self.name, mode or self.mode)
        else:
            raise ValueError("The file cannot be reopened.")
        return self

    def close(self) -> None:
        self.file.close()


def endswith_cr(line: str | bytes) -> bool:
    """Return True if line (a text or bytestring) ends with '\r'."""
    if isinstance(line, str):
        return line.endswith("\r")
    return line.endswith(b"\r")


def endswith_lf(line: str | bytes) -> bool:
    """Return True if line (a text or bytestring) ends with '\n'."""
    if isinstance(line, str):
        return line.endswith("\n")
    return line.endswith(b"\n")


def equals_lf(line: str | bytes) -> bool:
    """Return True if line (a text or bytestring) equals '\n'."""
    return line == ("\n" if isinstance(line, str) else b"\n")
