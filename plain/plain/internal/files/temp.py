"""
The temp module provides a NamedTemporaryFile that can be reopened in the same
process on any platform. Most platforms use the standard Python
tempfile.NamedTemporaryFile class, but Windows users are given a custom class.

This is needed because the Python implementation of NamedTemporaryFile uses the
O_TEMPORARY flag under Windows, which prevents the file from being reopened
if the same flag is not provided [1][2]. Note that this does not address the
more general issue of opening a file for writing and reading in multiple
processes in a manner that works across platforms.

The custom version of NamedTemporaryFile doesn't support the same keyword
arguments available in tempfile.NamedTemporaryFile.

1: https://mail.python.org/pipermail/python-list/2005-December/336957.html
2: https://bugs.python.org/issue14243
"""

from __future__ import annotations

import os
import tempfile
from collections.abc import Callable
from typing import TYPE_CHECKING

from plain.internal.files.utils import FileProxyMixin

if TYPE_CHECKING:
    from typing import Any

__all__ = (
    "NamedTemporaryFile",
    "gettempdir",
)


if os.name == "nt":

    class TemporaryFile(FileProxyMixin):
        """
        Temporary file object constructor that supports reopening of the
        temporary file in Windows.

        Unlike tempfile.NamedTemporaryFile from the standard library,
        __init__() doesn't support the 'delete', 'buffering', 'encoding', or
        'newline' keyword arguments.
        """

        def __init__(
            self,
            mode: str = "w+b",
            bufsize: int = -1,
            suffix: str = "",
            prefix: str = "",
            dir: str | None = None,
        ) -> None:
            fd, name = tempfile.mkstemp(suffix=suffix, prefix=prefix, dir=dir)
            self.name = name
            self.file = os.fdopen(fd, mode, bufsize)
            self.close_called = False

        # Because close can be called during shutdown
        # we need to cache os.unlink and access it
        # as self.unlink only
        unlink: Callable[[str], None] = os.unlink

        def close(self) -> None:
            if not self.close_called:
                self.close_called = True
                try:
                    self.file.close()
                except OSError:
                    pass
                try:
                    self.unlink(self.name)
                except OSError:
                    pass

        def __del__(self) -> None:
            self.close()

        def __enter__(self) -> TemporaryFile:
            self.file.__enter__()
            return self

        def __exit__(
            self,
            exc: type[BaseException] | None,
            value: BaseException | None,
            tb: Any,
        ) -> None:
            self.file.__exit__(exc, value, tb)

    NamedTemporaryFile = TemporaryFile
else:
    NamedTemporaryFile = tempfile.NamedTemporaryFile

gettempdir = tempfile.gettempdir
