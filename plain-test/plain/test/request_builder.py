"""Building a `Request` without sending it.

`build_request()` is the public function. The two it is made of are what
`Client` uses as well, so a request the client sends is encoded and built
exactly as one a test builds by hand.
"""

import json
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from plain.http import Request
from plain.json import PlainJSONEncoder
from plain.utils.http import parse_header_parameters, urlencode

from .encoding import encode_multipart

__all__ = ["build_request"]

_BOUNDARY = "BoUnDaRyStRiNg"
_MULTIPART_CONTENT = f"multipart/form-data; boundary={_BOUNDARY}"

# Where a request goes when its path doesn't say: https://testserver.
DEFAULT_SCHEME = "https"
DEFAULT_HOST = "testserver"
DEFAULT_PORTS = {"https": "443", "http": "80"}


def build_request(
    method: str,
    path: str,
    *,
    query_params: dict[str, Any] | None = None,
    form_data: dict[str, Any] | None = None,
    json_data: Any = None,
    body: bytes | str | None = None,
    files: dict[str, Any] | None = None,
    content_type: str | None = None,
    headers: dict[str, str] | None = None,
) -> Request:
    """
    Build a `Request` without sending it, to hand to a view or a middleware
    directly.

        request = build_request("POST", "/submit", form_data={"name": "Ada"})

    It takes the keywords `Client`'s methods take, and encodes the body the
    same way.

    `path` is a path, which makes a request to `https://testserver`. Pass a
    full URL when the scheme, host or port matter:

        request = build_request("GET", "http://testserver/")  # not HTTPS
    """
    encoded_body, encoded_content_type = encode_request_body(
        form_data=form_data,
        json_data=json_data,
        body=body,
        files=files,
        content_type=content_type,
    )
    return build_encoded_request(
        method,
        split_target(path, query_params=query_params),
        body=encoded_body,
        content_type=encoded_content_type,
        headers=headers,
    )


@dataclass(frozen=True)
class Target:
    """Where a request goes: the parts of the path or URL it was given."""

    scheme: str
    host: str
    port: str
    path: str
    query_string: str


def split_target(path: str, *, query_params: dict[str, Any] | None = None) -> Target:
    """Split a path, or a full http(s) URL, into where the request goes.

    A path goes to the default scheme and host. A URL names its own; its
    port is the one it gives, or its scheme's. A query string the path
    carries comes first, and `query_params` go after it.
    """
    parts = urlsplit(str(path))  # path can be lazy

    if parts.scheme in DEFAULT_PORTS:
        scheme = parts.scheme
        host = parts.hostname or DEFAULT_HOST
        port = str(parts.port) if parts.port else DEFAULT_PORTS[scheme]
    else:
        scheme = DEFAULT_SCHEME
        host = DEFAULT_HOST
        port = DEFAULT_PORTS[scheme]

    query_strings = [parts.query, urlencode(query_params or {}, doseq=True)]

    return Target(
        scheme=scheme,
        host=host,
        port=port,
        path=parts.path,
        query_string="&".join(part for part in query_strings if part),
    )


def build_encoded_request(
    method: str,
    target: Target,
    *,
    body: bytes,
    content_type: str,
    headers: dict[str, str] | None,
) -> Request:
    """Build a `Request` from a body that is already bytes."""
    all_headers: dict[str, str] = dict(headers or {})

    # Content headers follow the content type, not the byte count: a POST
    # of an empty form still declares what it is, with Content-Length: 0,
    # the same as a browser submitting a form with nothing filled in.
    # Requests with no body source at all (a GET) resolve to no content
    # type and get neither header.
    if content_type:
        all_headers["Content-Type"] = content_type
        all_headers["Content-Length"] = str(len(body))

    return Request(
        method=method,
        path=target.path,
        headers=all_headers,
        query_string=target.query_string,
        body=body,
        server_scheme=target.scheme,
        server_name=target.host,
        server_port=target.port,
        remote_addr="127.0.0.1",
    )


def encode_request_body(
    *,
    form_data: dict[str, Any] | None,
    json_data: Any,
    body: bytes | str | None,
    files: dict[str, Any] | None,
    content_type: str | None,
) -> tuple[bytes, str]:
    """
    Encode the body arguments into (bytes, content_type).

    Exactly one body source may be given: form_data (optionally with files),
    json_data, or a raw body. `content_type` only applies to a raw body.

    A form encodes the way a browser would: urlencoded, and multipart only
    when there are files. Views under test then see the content type they'd
    see in production.
    """
    sources = [
        form_data is not None or files is not None,
        json_data is not None,
        body is not None,
    ]
    if sum(sources) > 1:
        raise TypeError(
            "Pass only one of form_data/files, json_data, or body per request"
        )
    if content_type is not None and body is None:
        if not any(sources):
            # `post(path, content_type="application/json")` with nothing to
            # send. Building an empty body here would hand the view a b"" that
            # its content type says is parseable, and the failure would
            # surface somewhere further in. Say it at the call instead.
            raise TypeError(
                "content_type needs a body — pass body=... alongside it "
                '(body=b"" for a deliberately empty one)'
            )
        raise TypeError(
            "content_type only applies to a raw body — form_data and json_data set their own"
        )

    if form_data is not None:
        _refuse_files_in_form_data(form_data)

    if json_data is not None:
        return (
            json.dumps(json_data, cls=PlainJSONEncoder).encode(),
            "application/json",
        )

    if body is not None:
        resolved_content_type = content_type or "application/octet-stream"
        if isinstance(body, str):
            # Encode a string body with the charset the content type
            # declares, read the way `Request` reads it back, so the
            # payload bytes match what the request advertises. Bytes pass
            # through untouched.
            _, content_params = parse_header_parameters(resolved_content_type)
            body = body.encode(content_params.get("charset", "utf-8"))
        return (body, resolved_content_type)

    if files:
        # Files can only travel as multipart, and any form fields sent with
        # them ride along in the same body.
        merged: dict[str, Any] = dict(form_data or {})
        merged.update(files)
        return (
            encode_multipart(_BOUNDARY, merged),
            _MULTIPART_CONTENT,
        )

    if form_data is not None or files is not None:
        # A plain form — what a browser (and htmx) sends without a file input.
        return (
            urlencode(form_data or {}, doseq=True).encode(),
            "application/x-www-form-urlencoded",
        )

    return (b"", "")


def _refuse_files_in_form_data(form_data: dict[str, Any]) -> None:
    """
    A file in `form_data` would be sent as a text field holding the
    object's `repr`, and the view would find no file. Say where it goes.
    """
    for name, value in form_data.items():
        values = value if isinstance(value, list | tuple) else [value]
        for one in values:
            if _is_file_content(one):
                raise TypeError(
                    f"form_data[{name!r}] is {type(one).__name__}, which is a "
                    "file's content. A form's text fields go in form_data and "
                    f"its files go in files: files={{{name!r}: ...}}"
                )


def _is_file_content(value: Any) -> bool:
    if isinstance(value, bytes | bytearray | memoryview):
        return True
    # An open file, a BytesIO, an uploaded file: what can be read from.
    return callable(getattr(value, "read", None))
