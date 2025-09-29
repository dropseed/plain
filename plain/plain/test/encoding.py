from __future__ import annotations

import mimetypes
import os
from typing import Any

from plain.runtime import settings
from plain.utils.encoding import force_bytes
from plain.utils.itercompat import is_iterable


def encode_multipart(boundary: str, data: dict[str, Any]) -> bytes:
    """
    Encode multipart POST data from a dictionary of form values.

    The key will be used as the form data name; the value will be transmitted
    as content. If the value is a file, the contents of the file will be sent
    as an application/octet-stream; otherwise, str(value) will be sent.
    """
    lines: list[bytes] = []

    def to_bytes(s: str) -> bytes:
        return force_bytes(s, settings.DEFAULT_CHARSET)

    # Not by any means perfect, but good enough for our purposes.
    def is_file(thing: Any) -> bool:
        return hasattr(thing, "read") and callable(thing.read)

    # Each bit of the multipart form data could be either a form value or a
    # file, or a *list* of form values and/or files. Remember that HTTP field
    # names can be duplicated!
    for key, value in data.items():
        if value is None:
            raise TypeError(
                f"Cannot encode None for key '{key}' as POST data. Did you mean "
                "to pass an empty string or omit the value?"
            )
        elif is_file(value):
            lines.extend(encode_file(boundary, key, value))
        elif not isinstance(value, str) and is_iterable(value):
            for item in value:
                if is_file(item):
                    lines.extend(encode_file(boundary, key, item))
                else:
                    lines.extend(
                        to_bytes(val)
                        for val in [
                            f"--{boundary}",
                            f'Content-Disposition: form-data; name="{key}"',
                            "",
                            item,
                        ]
                    )
        else:
            lines.extend(
                to_bytes(val)
                for val in [
                    f"--{boundary}",
                    f'Content-Disposition: form-data; name="{key}"',
                    "",
                    value,
                ]
            )

    lines.extend(
        [
            to_bytes(f"--{boundary}--"),
            b"",
        ]
    )
    return b"\r\n".join(lines)


def encode_file(boundary: str, key: str, file: Any) -> list[bytes]:
    def to_bytes(s: str) -> bytes:
        return force_bytes(s, settings.DEFAULT_CHARSET)

    # file.name might not be a string. For example, it's an int for
    # tempfile.TemporaryFile().
    file_has_string_name = hasattr(file, "name") and isinstance(file.name, str)
    filename = os.path.basename(file.name) if file_has_string_name else ""

    if hasattr(file, "content_type"):
        content_type = file.content_type
    elif filename:
        content_type = mimetypes.guess_type(filename)[0]
    else:
        content_type = None

    if content_type is None:
        content_type = "application/octet-stream"
    filename = filename or key
    return [
        to_bytes(f"--{boundary}"),
        to_bytes(
            f'Content-Disposition: form-data; name="{key}"; filename="{filename}"'
        ),
        to_bytes(f"Content-Type: {content_type}"),
        b"",
        to_bytes(file.read()),
    ]
