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
import os
import random
import re
import socket
import time
import urllib.parse

# Server and Date aren't technically hop-by-hop
# headers, but they are in the purview of the
# origin server, so we drop them and add our own.
#
# In the future, concatenation server header values
# might be better, but nothing else does it and
# dropping them is easier.
hop_headers = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
    "server",
    "date",
}


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


def _error_response_bytes(
    status_int: int, reason: str, mesg: str, *, head: bool = False
) -> bytes:
    body = (
        "<html>\n"
        f"  <head><title>{reason}</title></head>\n"
        "  <body>\n"
        f"    <h1><p>{reason}</p></h1>\n"
        f"    {html.escape(mesg)}\n"
        "  </body>\n"
        "</html>\n"
    )

    # The load-shedding 503 explicitly invites a retry — tell
    # well-behaved clients how soon.
    retry_after = "Retry-After: 1\r\n" if status_int == 503 else ""
    response = (
        f"HTTP/1.1 {status_int} {reason}\r\n"
        f"Connection: close\r\n"
        f"{retry_after}"
        f"Content-Type: text/html\r\n"
        f"Content-Length: {len(body)}\r\n"
        f"\r\n"
        # A HEAD response keeps the Content-Length but sends no body
        # (RFC 9110 9.3.2).
        f"{'' if head else body}"
    )
    return response.encode("latin1")


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
