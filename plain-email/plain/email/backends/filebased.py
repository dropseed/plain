"""Email backend that writes messages to a file."""

from __future__ import annotations

import datetime
import os
from typing import TYPE_CHECKING, Any

from plain.exceptions import ImproperlyConfigured
from plain.runtime import settings

from .console import EmailBackend as ConsoleEmailBackend

if TYPE_CHECKING:
    from ..message import EmailMessage


class EmailBackend(ConsoleEmailBackend):
    file_path: str  # Set during __init__, validated to be non-None

    def __init__(self, *args: Any, file_path: str | None = None, **kwargs: Any) -> None:
        self._fname: str | None = None
        _file_path: str | None = file_path or getattr(settings, "EMAIL_FILE_PATH", None)
        if not _file_path:
            raise ImproperlyConfigured(
                "EMAIL_FILE_PATH must be set for the filebased email backend"
            )
        self.file_path = os.path.abspath(_file_path)
        try:
            os.makedirs(self.file_path, exist_ok=True)
        except FileExistsError:
            raise ImproperlyConfigured(
                f"Path for saving email messages exists, but is not a directory: {self.file_path}"
            )
        except OSError as err:
            raise ImproperlyConfigured(
                f"Could not create directory for saving email messages: {self.file_path} ({err})"
            )
        # Make sure that self.file_path is writable.
        if not os.access(self.file_path, os.W_OK):
            raise ImproperlyConfigured(
                f"Could not write to directory: {self.file_path}"
            )
        # Finally, call super().
        # Since we're using the console-based backend as a base,
        # force the stream to be None, so we don't default to stdout
        kwargs["stream"] = None
        super().__init__(*args, **kwargs)

    def write_message(self, message: EmailMessage) -> None:
        assert self.stream is not None, "stream should be opened before writing"
        self.stream.write(message.message().as_bytes() + b"\n")
        self.stream.write(b"-" * 79)
        self.stream.write(b"\n")

    def _get_filename(self) -> str:
        """Return a unique file name."""
        if self._fname is None:
            timestamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
            fname = f"{timestamp}-{abs(id(self))}.log"
            self._fname = os.path.join(self.file_path, fname)
        return self._fname

    def open(self) -> bool:
        if self.stream is None:
            self.stream = open(self._get_filename(), "ab")
            return True
        return False

    def close(self) -> None:
        try:
            if self.stream is not None:
                self.stream.close()
        finally:
            self.stream = None
