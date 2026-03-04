from __future__ import annotations

#
#
# This file is part of gunicorn released under the MIT license.
# See the LICENSE for more information.
#
# Vendored and modified for Plain.
import io
import logging
import os
import re
import socket
from collections.abc import Iterator
from typing import TYPE_CHECKING, Any
from urllib.parse import quote, unquote_to_bytes

from plain.http import FileResponse
from plain.http import Request as HttpRequest

from .. import util
from .errors import ConfigurationProblem, InvalidHeader, InvalidHeaderName
from .message import TOKEN_RE

if TYPE_CHECKING:
    from .message import Request as ServerRequest

# Send files in at most 1GB blocks as some operating systems can have problems
# with sending files in blocks over 2GB.
BLKSIZE = 0x3FFFFFFF

# RFC9110 5.5: field-vchar = VCHAR / obs-text
# RFC4234 B.1: VCHAR = 0x21-x07E = printable ASCII
HEADER_VALUE_RE = re.compile(r"[ \t\x21-\x7e\x80-\xff]*")

log = logging.getLogger(__name__)


class FileWrapper:
    def __init__(self, filelike: Any, blksize: int = 8192) -> None:
        self.filelike = filelike
        self.blksize = blksize
        if hasattr(filelike, "close"):
            self.close = filelike.close

    def __getitem__(self, key: int) -> bytes:
        data = self.filelike.read(self.blksize)
        if data:
            return data
        raise IndexError


def create_request(
    req: ServerRequest,
    sock: socket.socket,
    client: str | bytes | tuple[str, int],
    server: str | tuple[str, int],
) -> HttpRequest:
    """Build a plain.http.Request directly from the server's parsed HTTP message."""

    # Extract headers from server message (list of (UPPER_NAME, value) tuples)
    headers: dict[str, str] = {}
    host = None
    script_name = os.environ.get("SCRIPT_NAME", "")

    for hdr_name, hdr_value in req.headers:
        if hdr_name == "EXPECT":
            if hdr_value.lower() == "100-continue":
                sock.send(b"HTTP/1.1 100 Continue\r\n\r\n")
        elif hdr_name == "HOST":
            host = hdr_value
        elif hdr_name == "SCRIPT_NAME":
            script_name = hdr_value

        # Handle duplicate headers by joining with comma
        if hdr_name in headers:
            headers[hdr_name] = f"{headers[hdr_name]},{hdr_value}"
        else:
            headers[hdr_name] = hdr_value

    # Remote address
    if isinstance(client, str):
        remote_addr = client
    elif isinstance(client, bytes):
        remote_addr = client.decode()
    else:
        remote_addr = client[0]

    # Server name/port
    server_name, server_port = _resolve_server_address(server, host, req.scheme)

    # Path
    raw_path = req.path or ""
    if script_name:
        if not raw_path.startswith(script_name):
            raise ConfigurationProblem(
                f"Request path {raw_path!r} does not start with SCRIPT_NAME {script_name!r}"
            )
        raw_path = raw_path[len(script_name) :]

    # Decode path: percent-decode then handle broken UTF-8
    path_bytes = unquote_to_bytes(raw_path)
    path_info = _decode_path(path_bytes) or "/"
    path = "{}/{}".format(script_name.rstrip("/"), path_info.replace("/", "", 1))

    request = HttpRequest(
        method=(req.method or "GET").upper(),
        path=path,
        headers=headers,
        query_string=req.query or "",
        server_scheme=req.scheme,
        server_name=server_name,
        server_port=server_port,
        remote_addr=remote_addr,
        path_info=path_info,
    )

    # Body stream
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


class Response:
    def __init__(
        self, req: ServerRequest, sock: socket.socket, *, is_ssl: bool = False
    ) -> None:
        self.req = req
        self.sock = sock
        self.is_ssl = is_ssl
        self.version = "plain"
        self.status: str | None = None
        self.chunked = False
        self.must_close = False
        self.headers: list[tuple[str, str]] = []
        self.headers_sent = False
        self.response_length: int | None = None
        self.sent = 0
        self.upgrade = False
        self.status_code: int | None = None

    def force_close(self) -> None:
        self.must_close = True

    def should_close(self) -> bool:
        if self.must_close or self.req.should_close():
            return True
        if self.response_length is not None or self.chunked:
            return False
        if self.req.method == "HEAD":
            return False
        if self.status_code is not None and (
            self.status_code < 200 or self.status_code in (204, 304)
        ):
            return False
        return True

    def set_status_and_headers(
        self,
        status: str,
        headers: list[tuple[str, str]],
    ) -> None:
        if self.status is not None:
            raise AssertionError("Response headers already set!")

        self.status = status

        try:
            self.status_code = int(self.status.split()[0])
        except ValueError:
            self.status_code = None

        self.process_headers(headers)
        self.chunked = self.is_chunked()

    def process_headers(self, headers: list[tuple[str, str]]) -> None:
        for name, value in headers:
            if not isinstance(name, str):
                raise TypeError(f"{name!r} is not a string")

            if not TOKEN_RE.fullmatch(name):
                raise InvalidHeaderName(f"{name!r}")

            if not isinstance(value, str):
                raise TypeError(f"{value!r} is not a string")

            if not HEADER_VALUE_RE.fullmatch(value):
                raise InvalidHeader(f"{value!r}")

            # RFC9110 5.5
            value = value.strip(" \t")
            lname = name.lower()
            if lname == "content-length":
                self.response_length = int(value)
            elif util.is_hoppish(name):
                if lname == "connection":
                    # handle websocket
                    if value.lower() == "upgrade":
                        self.upgrade = True
                elif lname == "upgrade":
                    if value.lower() == "websocket":
                        self.headers.append((name, value))

                # ignore hopbyhop headers
                continue
            self.headers.append((name, value))

    def is_chunked(self) -> bool:
        # Only use chunked responses when the client is
        # speaking HTTP/1.1 or newer and there was
        # no Content-Length header set.
        if self.response_length is not None:
            return False
        elif self.req.version <= (1, 0):
            return False
        elif self.req.method == "HEAD":
            # Responses to a HEAD request MUST NOT contain a response body.
            return False
        elif self.status_code is not None and self.status_code in (204, 304):
            # Do not use chunked responses when the response is guaranteed to
            # not have a response body.
            return False
        return True

    def default_headers(self) -> list[str]:
        # set the connection header
        if self.upgrade:
            connection = "upgrade"
        elif self.should_close():
            connection = "close"
        else:
            connection = "keep-alive"

        headers = [
            f"HTTP/{self.req.version[0]}.{self.req.version[1]} {self.status}\r\n",
            f"Server: {self.version}\r\n",
            f"Date: {util.http_date()}\r\n",
            f"Connection: {connection}\r\n",
        ]
        if self.chunked:
            headers.append("Transfer-Encoding: chunked\r\n")
        return headers

    def send_headers(self) -> None:
        if self.headers_sent:
            return None
        tosend = self.default_headers()
        tosend.extend([f"{k}: {v}\r\n" for k, v in self.headers])

        header_str = "{}\r\n".format("".join(tosend))
        util.write(self.sock, util.to_bytestring(header_str, "latin-1"))
        self.headers_sent = True
        return None

    def write(self, arg: bytes) -> None:
        self.send_headers()
        if not isinstance(arg, bytes):
            raise TypeError(f"{arg!r} is not a byte")
        arglen = len(arg)
        tosend = arglen
        if self.response_length is not None:
            if self.sent >= self.response_length:
                # Never write more than self.response_length bytes
                return None

            tosend = min(self.response_length - self.sent, tosend)
            if tosend < arglen:
                arg = arg[:tosend]

        # Sending an empty chunk signals the end of the
        # response and prematurely closes the response
        if self.chunked and tosend == 0:
            return None

        self.sent += tosend
        util.write(self.sock, arg, self.chunked)
        return None

    def can_sendfile(self) -> bool:
        from plain.runtime import settings

        return settings.SERVER_SENDFILE

    def sendfile(self, respiter: FileWrapper) -> bool:
        if self.is_ssl or not self.can_sendfile():
            return False

        if not util.has_fileno(respiter.filelike):
            return False

        fileno = respiter.filelike.fileno()
        try:
            offset = os.lseek(fileno, 0, os.SEEK_CUR)
            if self.response_length is None:
                filesize = os.fstat(fileno).st_size
                nbytes = filesize - offset
            else:
                nbytes = self.response_length
        except (OSError, io.UnsupportedOperation):
            return False

        self.send_headers()

        if self.is_chunked():
            chunk_size = f"{nbytes:X}\r\n"
            self.sock.sendall(chunk_size.encode("utf-8"))
        if nbytes > 0:
            self.sock.sendfile(respiter.filelike, offset=offset, count=nbytes)

        if self.is_chunked():
            self.sock.sendall(b"\r\n")

        os.lseek(fileno, offset, os.SEEK_SET)

        return True

    def write_file(self, respiter: FileWrapper | Iterator[bytes]) -> None:
        if isinstance(respiter, FileWrapper):
            if not self.sendfile(respiter):
                for item in respiter:
                    self.write(item)
        else:
            for item in respiter:
                self.write(item)

    def write_response(self, http_response: Any) -> None:
        """Write a plain.http.ResponseBase directly to the socket."""
        status = f"{http_response.status_code} {http_response.reason_phrase}"
        response_headers = [
            *((k, v) for k, v in http_response.headers.items() if v is not None),
            *(
                ("Set-Cookie", c.output(header=""))
                for c in http_response.cookies.values()
            ),
        ]

        self.set_status_and_headers(status, response_headers)

        if (
            isinstance(http_response, FileResponse)
            and http_response.file_to_stream is not None
        ):
            file_wrapper = FileWrapper(
                http_response.file_to_stream, http_response.block_size
            )
            # Patch close so the response gets properly cleaned up
            http_response.file_to_stream.close = http_response.close
            self.write_file(file_wrapper)
        else:
            for chunk in http_response:
                self.write(chunk)

        self.close()

    def close(self) -> None:
        if not self.headers_sent:
            self.send_headers()
        if self.chunked:
            util.write_chunk(self.sock, b"")
