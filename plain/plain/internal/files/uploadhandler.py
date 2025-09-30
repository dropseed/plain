"""
Base file upload handler classes, and the built-in concrete subclasses
"""

from __future__ import annotations

import os
from io import BytesIO
from typing import TYPE_CHECKING

from plain.internal.files.uploadedfile import (
    InMemoryUploadedFile,
    TemporaryUploadedFile,
    UploadedFile,
)
from plain.runtime import settings
from plain.utils.module_loading import import_string

if TYPE_CHECKING:
    from typing import Any

    from plain.http import Request

__all__ = [
    "UploadFileException",
    "StopUpload",
    "SkipFile",
    "FileUploadHandler",
    "TemporaryFileUploadHandler",
    "MemoryFileUploadHandler",
    "load_handler",
    "StopFutureHandlers",
]


class UploadFileException(Exception):
    """
    Any error having to do with uploading files.
    """

    pass


class StopUpload(UploadFileException):
    """
    This exception is raised when an upload must abort.
    """

    def __init__(self, connection_reset: bool = False) -> None:
        """
        If ``connection_reset`` is ``True``, Plain knows will halt the upload
        without consuming the rest of the upload. This will cause the browser to
        show a "connection reset" error.
        """
        self.connection_reset = connection_reset

    def __str__(self) -> str:
        if self.connection_reset:
            return "StopUpload: Halt current upload."
        else:
            return "StopUpload: Consume request data, then halt."


class SkipFile(UploadFileException):
    """
    This exception is raised by an upload handler that wants to skip a given file.
    """

    pass


class StopFutureHandlers(UploadFileException):
    """
    Upload handlers that have handled a file and do not want future handlers to
    run should raise this exception instead of returning None.
    """

    pass


class FileUploadHandler:
    """
    Base class for streaming upload handlers.
    """

    chunk_size = 64 * 2**10  # : The default chunk size is 64 KB.

    def __init__(self, request: Request | None = None) -> None:
        self.file_name = None
        self.content_type = None
        self.content_length = None
        self.charset = None
        self.content_type_extra = None
        self.request = request

    def handle_raw_input(
        self,
        input_data: Any,
        meta: dict[str, Any],
        content_length: int,
        boundary: bytes,
        encoding: str | None = None,
    ) -> None:
        """
        Handle the raw input from the client.

        Parameters:

            :input_data:
                An object that supports reading via .read().
            :meta:
                ``request.meta``.
            :content_length:
                The (integer) value of the Content-Length header from the
                client.
            :boundary: The boundary from the Content-Type header. Be sure to
                prepend two '--'.
        """
        pass

    def new_file(
        self,
        field_name: str,
        file_name: str,
        content_type: str,
        content_length: int,
        charset: str | None = None,
        content_type_extra: dict[str, str] | None = None,
    ) -> None:
        """
        Signal that a new file has been started.

        Warning: As with any data from the client, you should not trust
        content_length (and sometimes won't even get it).
        """
        self.field_name = field_name
        self.file_name = file_name
        self.content_type = content_type
        self.content_length = content_length
        self.charset = charset
        self.content_type_extra = content_type_extra

    def receive_data_chunk(self, raw_data: bytes, start: int) -> bytes | None:
        """
        Receive data from the streamed upload parser. ``start`` is the position
        in the file of the chunk.
        """
        raise NotImplementedError(
            "subclasses of FileUploadHandler must provide a receive_data_chunk() method"
        )

    def file_complete(self, file_size: int) -> UploadedFile | None:
        """
        Signal that a file has completed. File size corresponds to the actual
        size accumulated by all the chunks.

        Subclasses should return a valid ``UploadedFile`` object.
        """
        raise NotImplementedError(
            "subclasses of FileUploadHandler must provide a file_complete() method"
        )

    def upload_complete(self) -> None:
        """
        Signal that the upload is complete. Subclasses should perform cleanup
        that is necessary for this handler.
        """
        pass

    def upload_interrupted(self) -> None:
        """
        Signal that the upload was interrupted. Subclasses should perform
        cleanup that is necessary for this handler.
        """
        pass


class TemporaryFileUploadHandler(FileUploadHandler):
    """
    Upload handler that streams data into a temporary file.
    """

    def new_file(self, *args: Any, **kwargs: Any) -> None:
        """
        Create the file object to append to as data is coming in.
        """
        super().new_file(*args, **kwargs)
        self.file = TemporaryUploadedFile(
            self.file_name, self.content_type, 0, self.charset, self.content_type_extra
        )

    def receive_data_chunk(self, raw_data: bytes, start: int) -> None:
        self.file.write(raw_data)
        return None

    def file_complete(self, file_size: int) -> TemporaryUploadedFile:
        self.file.seek(0)
        self.file.size = file_size
        return self.file

    def upload_interrupted(self) -> None:
        if hasattr(self, "file"):
            temp_location = self.file.temporary_file_path()
            try:
                self.file.close()
                os.remove(temp_location)
            except FileNotFoundError:
                pass


class MemoryFileUploadHandler(FileUploadHandler):
    """
    File upload handler to stream uploads into memory (used for small files).
    """

    def handle_raw_input(
        self,
        input_data: Any,
        meta: dict[str, Any],
        content_length: int,
        boundary: bytes,
        encoding: str | None = None,
    ) -> None:
        """
        Use the content_length to signal whether or not this handler should be
        used.
        """
        # Check the content-length header to see if we should
        # If the post is too large, we cannot use the Memory handler.
        self.activated = content_length <= settings.FILE_UPLOAD_MAX_MEMORY_SIZE

    def new_file(self, *args: Any, **kwargs: Any) -> None:
        super().new_file(*args, **kwargs)
        if self.activated:
            self.file = BytesIO()
            raise StopFutureHandlers()

    def receive_data_chunk(self, raw_data: bytes, start: int) -> bytes | None:
        """Add the data to the BytesIO file."""
        if self.activated:
            self.file.write(raw_data)
            return None
        else:
            return raw_data

    def file_complete(self, file_size: int) -> InMemoryUploadedFile | None:
        """Return a file object if this handler is activated."""
        if not self.activated:
            return None

        self.file.seek(0)
        return InMemoryUploadedFile(
            file=self.file,
            field_name=self.field_name,
            name=self.file_name,
            content_type=self.content_type,
            size=file_size,
            charset=self.charset,
            content_type_extra=self.content_type_extra,
        )


def load_handler(path: str, *args: Any, **kwargs: Any) -> FileUploadHandler:
    """
    Given a path to a handler, return an instance of that handler.

    E.g.::
        >>> from plain.http import Request
        >>> request = Request()
        >>> load_handler(
        ...     'plain.internal.files.uploadhandler.TemporaryFileUploadHandler',
        ...     request,
        ... )
        <TemporaryFileUploadHandler object at 0x...>
    """
    return import_string(path)(*args, **kwargs)
