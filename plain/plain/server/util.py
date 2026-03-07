from __future__ import annotations

#
#
# This file is part of gunicorn released under the MIT license.
# See the LICENSE for more information.
#
# Vendored and modified for Plain.
import email.utils
import fcntl
import html
import io
import os
import random
import re
import socket
import time
import urllib.parse
from typing import Any

# Server and Date aren't technically hop-by-hop
# headers, but they are in the purview of the
# origin server, so we drop them and add our own.
#
# In the future, concatenation server header values
# might be better, but nothing else does it and
# dropping them is easier.
hop_headers = set(
    """
    connection keep-alive proxy-authenticate proxy-authorization
    te trailers transfer-encoding upgrade
    server date
    """.split()
)


def is_ipv6(addr: str) -> bool:
    try:
        socket.inet_pton(socket.AF_INET6, addr)
    except OSError:  # not a valid address
        return False
    except ValueError:  # ipv6 not supported on this platform
        return False
    return True


def parse_address(netloc: str, default_port: str = "8000") -> str | tuple[str, int]:
    if re.match(r"unix:(//)?", netloc):
        return re.split(r"unix:(//)?", netloc)[-1]

    if netloc.startswith("tcp://"):
        netloc = netloc.split("tcp://")[1]
    host, port = netloc, default_port

    if "[" in netloc and "]" in netloc:
        host = netloc.split("]")[0][1:]
        port = (netloc.split("]:") + [default_port])[1]
    elif ":" in netloc:
        host, port = (netloc.split(":") + [default_port])[:2]
    elif netloc == "":
        host, port = "0.0.0.0", default_port

    try:
        port = int(port)
    except ValueError:
        raise RuntimeError(f"{port!r} is not a valid port number.")

    return host.lower(), port


def close_on_exec(fd: int) -> None:
    flags = fcntl.fcntl(fd, fcntl.F_GETFD)
    flags |= fcntl.FD_CLOEXEC
    fcntl.fcntl(fd, fcntl.F_SETFD, flags)


def set_non_blocking(fd: int) -> None:
    flags = fcntl.fcntl(fd, fcntl.F_GETFL) | os.O_NONBLOCK
    fcntl.fcntl(fd, fcntl.F_SETFL, flags)


def close(sock: socket.socket) -> None:
    try:
        sock.close()
    except OSError:
        pass


def write_chunk(sock: socket.socket, data: str | bytes) -> None:
    if isinstance(data, str):
        data = data.encode("utf-8")
    chunk_size = f"{len(data):X}\r\n"
    chunk = b"".join([chunk_size.encode("utf-8"), data, b"\r\n"])
    sock.sendall(chunk)


def write(sock: socket.socket, data: str | bytes, chunked: bool = False) -> None:
    if chunked:
        return write_chunk(sock, data)
    if isinstance(data, str):
        data = data.encode("utf-8")
    sock.sendall(data)


def write_nonblock(
    sock: socket.socket, data: str | bytes, chunked: bool = False
) -> None:
    timeout = sock.gettimeout()
    if timeout != 0.0:
        try:
            sock.setblocking(False)
            return write(sock, data, chunked)
        finally:
            sock.setblocking(True)
    else:
        return write(sock, data, chunked)


def _error_response_bytes(status_int: int, reason: str, mesg: str) -> bytes:
    body = (
        "<html>\n"
        f"  <head><title>{reason}</title></head>\n"
        "  <body>\n"
        f"    <h1><p>{reason}</p></h1>\n"
        f"    {html.escape(mesg)}\n"
        "  </body>\n"
        "</html>\n"
    )

    response = (
        f"HTTP/1.1 {status_int} {reason}\r\n"
        f"Connection: close\r\n"
        f"Content-Type: text/html\r\n"
        f"Content-Length: {len(body)}\r\n"
        f"\r\n"
        f"{body}"
    )
    return response.encode("latin1")


def write_error(sock: socket.socket, status_int: int, reason: str, mesg: str) -> None:
    write_nonblock(sock, _error_response_bytes(status_int, reason, mesg))


async def async_write_error(
    sock: socket.socket, status_int: int, reason: str, mesg: str
) -> None:
    import asyncio

    loop = asyncio.get_running_loop()
    await loop.sock_sendall(sock, _error_response_bytes(status_int, reason, mesg))


def http_date(timestamp: float | None = None) -> str:
    """Return the current date and time formatted for a message header."""
    if timestamp is None:
        timestamp = time.time()
    s = email.utils.formatdate(timestamp, localtime=False, usegmt=True)
    return s


def is_hoppish(header: str) -> bool:
    return header.lower().strip() in hop_headers


def seed() -> None:
    try:
        random.seed(os.urandom(64))
    except NotImplementedError:
        random.seed(f"{time.time()}.{os.getpid()}")


def to_bytestring(value: str | bytes, encoding: str = "utf8") -> bytes:
    """Converts a string argument to a byte string"""
    if isinstance(value, bytes):
        return value
    if not isinstance(value, str):
        raise TypeError(f"{value!r} is not a string")

    return value.encode(encoding)


def has_fileno(obj: Any) -> bool:
    if not hasattr(obj, "fileno"):
        return False

    # check BytesIO case and maybe others
    try:
        obj.fileno()
    except (AttributeError, OSError, io.UnsupportedOperation):
        return False

    return True


def make_fail_handler(msg: str | bytes) -> Any:
    """Create a handler that returns a 500 error for all requests."""
    msg = to_bytestring(msg)

    class FailHandler:
        async def handle(self, request: Any, executor: Any) -> Any:
            from plain.http import Response

            return Response(msg, status_code=500, content_type="text/plain")

    return FailHandler()


def split_request_uri(uri: str) -> urllib.parse.SplitResult:
    if uri.startswith("//"):
        # When the path starts with //, urlsplit considers it as a
        # relative uri while the RFC says we should consider it as abs_path
        # http://www.w3.org/Protocols/rfc2616/rfc2616-sec5.html#sec5.1.2
        # We use temporary dot prefix to workaround this behaviour
        parts = urllib.parse.urlsplit("." + uri)
        return parts._replace(path=parts.path[1:])

    return urllib.parse.urlsplit(uri)


def bytes_to_str(b: str | bytes) -> str:
    if isinstance(b, str):
        return b
    return str(b, "latin1")
