from __future__ import annotations

from typing import TYPE_CHECKING, Any
from urllib.parse import quote, unquote_to_bytes

from plain.http import ContentTooLargeError413
from plain.http import Request as HttpRequest

if TYPE_CHECKING:
    from .body import Body
    from .message import Request as ServerRequest


class CappedBodyStream:
    """Body stream that raises once more than max_size bytes are read.

    Backstop for SERVER_MAX_REQUEST_BODY_SIZE on bodies with no declared
    Content-Length (chunked): those can't be rejected from the headers,
    so the cap is enforced as the app reads. Declared-length bodies are
    rejected before the body is read instead (h1 fail-fast), so h1 only
    attaches this wrapper to chunked requests.
    """

    def __init__(self, stream: Body, max_size: int) -> None:
        self._stream = stream
        self._max_size = max_size
        self._bytes_read = 0

    def _count(self, data: bytes) -> bytes:
        self._bytes_read += len(data)
        if self._bytes_read > self._max_size:
            raise ContentTooLargeError413(
                "Request body exceeded settings.SERVER_MAX_REQUEST_BODY_SIZE."
            )
        return data

    def _bound(self) -> int:
        # One byte past the remaining allowance, so an over-cap body
        # raises instead of silently truncating at the cap.
        return self._max_size - self._bytes_read + 1

    def read(self, size: int | None = None) -> bytes:
        if size is None or size < 0:
            # Read-to-EOF (None and negative sizes both mean that to the
            # underlying Body) in allowance-bounded pieces: handing the
            # stream an unbounded read would materialize an over-cap body
            # in full before the count could raise — accounting, not a
            # memory bound.
            pieces = []
            while True:
                data = self._count(self._stream.read(self._bound()))
                if not data:
                    return b"".join(pieces)
                pieces.append(data)
        return self._count(self._stream.read(min(size, self._bound())))

    def readline(self, size: int | None = None) -> bytes:
        bound = self._bound()
        if size is None or size < 0 or size > bound:
            size = bound
        return self._count(self._stream.readline(size))

    def close(self) -> None:
        self._stream.close()


def _merge_headers(raw_headers: list[tuple[str, str]]) -> dict[str, str]:
    """Merge a list of (UPPER_NAME, value) header tuples into a dict.

    Duplicate headers are joined with comma, except COOKIE which uses '; '
    per RFC 9113 Section 8.2.3.
    """
    headers: dict[str, str] = {}
    for name, value in raw_headers:
        if name in headers:
            sep = "; " if name == "COOKIE" else ","
            headers[name] = f"{headers[name]}{sep}{value}"
        else:
            headers[name] = value
    return headers


def _resolve_remote_addr(client: str | bytes | tuple[str, int] | Any) -> str:
    """Extract a string remote address from a client identifier."""
    if isinstance(client, str):
        return client
    elif isinstance(client, bytes):
        return client.decode()
    elif isinstance(client, tuple):
        return client[0]
    return str(client)


def _resolve_path(raw_path: str) -> str:
    """Decode a raw request path to a UTF-8 string, defaulting to '/'."""
    path_bytes = unquote_to_bytes(raw_path)
    return _decode_path(path_bytes) or "/"


def create_request(
    req: ServerRequest,
    client: str | bytes | tuple[str, int],
    server: str | tuple[str, int],
    *,
    max_request_body: int | None,
) -> HttpRequest:
    """Build a plain.http.Request directly from the server's parsed HTTP message."""

    # Extract Host header (100-continue is handled during async body reading)
    host = None
    for hdr_name, hdr_value in req.headers:
        if hdr_name == "HOST":
            host = hdr_value

    headers = _merge_headers(req.headers)
    remote_addr = _resolve_remote_addr(client)
    server_name, server_port = _resolve_server_address(server, host, req.scheme)
    path = _resolve_path(req.path or "")

    request = HttpRequest(
        method=(req.method or "GET").upper(),
        path=path,
        headers=headers,
        query_string=req.query or "",
        server_scheme=req.scheme,
        server_name=server_name,
        server_port=server_port,
        remote_addr=remote_addr,
    )

    # Body stream — set by the message parser before this point.
    assert req.body is not None
    if max_request_body is not None:
        request._stream = CappedBodyStream(req.body, max_request_body)
    else:
        request._stream = req.body
    request._read_started = False

    return request


def _resolve_server_address(
    server: str | tuple[str, int],
    host: str | None,
    scheme: str,
) -> tuple[str, str]:
    """Resolve server name and port from the server address and Host header."""
    if isinstance(server, str):
        parts = server.split(":")
        if len(parts) == 1:
            # unix socket
            if host:
                host_parts = host.split(":")
                if len(host_parts) == 1:
                    default_port = (
                        "443" if scheme == "https" else "80" if scheme == "http" else ""
                    )
                    return host_parts[0], default_port
                return host_parts[0], host_parts[1]
            return parts[0], ""
        return parts[0], parts[1]
    return str(server[0]), str(server[1])


def _decode_path(path_bytes: bytes) -> str:
    """Decode percent-decoded path bytes to a UTF-8 string.

    Handles broken UTF-8 by repercent-encoding invalid sequences.
    """
    while True:
        try:
            return path_bytes.decode()
        except UnicodeDecodeError as e:
            repercent = quote(path_bytes[e.start : e.end], safe=b"/#%[]=:;$&()+,!?*@'~")
            path_bytes = (
                path_bytes[: e.start] + repercent.encode() + path_bytes[e.end :]
            )
