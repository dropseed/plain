from __future__ import annotations

import os
import pathlib
from typing import TYPE_CHECKING

from plain.exceptions import SuspiciousFileOperation

if TYPE_CHECKING:
    from collections.abc import Iterator
    from typing import Any


def validate_file_name(name: str, allow_relative_path: bool = False) -> str:
    # Remove potentially dangerous names
    if os.path.basename(name) in {"", ".", ".."}:
        raise SuspiciousFileOperation(f"Could not derive file name from '{name}'")

    if allow_relative_path:
        # Use PurePosixPath() because this branch is checked only in
        # FileField.generate_filename() where all file paths are expected to be
        # Unix style (with forward slashes).
        path = pathlib.PurePosixPath(name)
        if path.is_absolute() or ".." in path.parts:
            raise SuspiciousFileOperation(
                f"Detected path traversal attempt in '{name}'"
            )
    elif name != os.path.basename(name):
        raise SuspiciousFileOperation(f"File name '{name}' includes path elements")

    return name


class FileProxyMixin:
    """
    A mixin class used to forward file methods to an underlying file
    object.  The internal file object has to be called "file"::

        class FileProxy(FileProxyMixin):
            def __init__(self, file):
                self.file = file
    """

    encoding = property(lambda self: self.file.encoding)
    fileno = property(lambda self: self.file.fileno)
    flush = property(lambda self: self.file.flush)
    isatty = property(lambda self: self.file.isatty)
    newlines = property(lambda self: self.file.newlines)
    read = property(lambda self: self.file.read)
    readinto = property(lambda self: self.file.readinto)
    readline = property(lambda self: self.file.readline)
    readlines = property(lambda self: self.file.readlines)
    seek = property(lambda self: self.file.seek)
    tell = property(lambda self: self.file.tell)
    truncate = property(lambda self: self.file.truncate)
    write = property(lambda self: self.file.write)
    writelines = property(lambda self: self.file.writelines)

    @property
    def closed(self) -> bool:
        return not self.file or self.file.closed

    def readable(self) -> bool:
        if self.closed:
            return False
        if hasattr(self.file, "readable"):
            return self.file.readable()
        return True

    def writable(self) -> bool:
        if self.closed:
            return False
        if hasattr(self.file, "writable"):
            return self.file.writable()
        return "w" in getattr(self.file, "mode", "")

    def seekable(self) -> bool:
        if self.closed:
            return False
        if hasattr(self.file, "seekable"):
            return self.file.seekable()
        return True

    def __iter__(self) -> Iterator[Any]:
        return iter(self.file)
