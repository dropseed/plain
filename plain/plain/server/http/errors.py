from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .message import Message

#
#
# This file is part of gunicorn released under the MIT license.
# See the LICENSE for more information.
#
# Vendored and modified for Plain.

# We don't need to call super() in __init__ methods of our
# BaseException and Exception classes because we also define
# our own __str__ methods so there is no need to pass 'message'
# to the base class to get a meaningful output from 'str(exc)'.
# pylint: disable=super-init-not-called


class ParseException(Exception):
    pass


class NoMoreData(IOError):
    def __init__(self, buf: bytes | None = None):
        self.buf = buf

    def __str__(self) -> str:
        return f"No more data after: {self.buf!r}"


class ConfigurationProblem(ParseException):
    def __init__(self, info: str):
        self.info = info
        self.code = 500

    def __str__(self) -> str:
        return f"Configuration problem: {self.info}"


class InvalidRequestLine(ParseException):
    def __init__(self, req: str):
        self.req = req
        self.code = 400

    def __str__(self) -> str:
        return f"Invalid HTTP request line: {self.req!r}"


class InvalidRequestMethod(ParseException):
    def __init__(self, method: str):
        self.method = method

    def __str__(self) -> str:
        return f"Invalid HTTP method: {self.method!r}"


class InvalidHTTPVersion(ParseException):
    def __init__(self, version: str | tuple[int, int]):
        self.version = version

    def __str__(self) -> str:
        return f"Invalid HTTP Version: {self.version!r}"


class InvalidHeader(ParseException):
    def __init__(self, hdr: str, req: Message | None = None):
        self.hdr = hdr
        self.req = req

    def __str__(self) -> str:
        return f"Invalid HTTP Header: {self.hdr!r}"


class ObsoleteFolding(ParseException):
    def __init__(self, hdr: str):
        self.hdr = hdr

    def __str__(self) -> str:
        return f"Obsolete line folding is unacceptable: {self.hdr!r}"


class InvalidHeaderName(ParseException):
    def __init__(self, hdr: str):
        self.hdr = hdr

    def __str__(self) -> str:
        return f"Invalid HTTP header name: {self.hdr!r}"


class UnsupportedTransferCoding(ParseException):
    def __init__(self, hdr: str):
        self.hdr = hdr
        self.code = 501

    def __str__(self) -> str:
        return f"Unsupported transfer coding: {self.hdr!r}"


class InvalidChunkSize(IOError):
    def __init__(self, data: bytes):
        self.data = data

    def __str__(self) -> str:
        return f"Invalid chunk size: {self.data!r}"


class ChunkMissingTerminator(IOError):
    def __init__(self, term: bytes):
        self.term = term

    def __str__(self) -> str:
        return f"Invalid chunk terminator is not '\\r\\n': {self.term!r}"


class LimitRequestLine(ParseException):
    def __init__(self, size: int, max_size: int):
        self.size = size
        self.max_size = max_size

    def __str__(self) -> str:
        return f"Request Line is too large ({self.size} > {self.max_size})"


class LimitRequestHeaders(ParseException):
    def __init__(self, msg: str):
        self.msg = msg

    def __str__(self) -> str:
        return self.msg


class InvalidProxyLine(ParseException):
    def __init__(self, line: str):
        self.line = line
        self.code = 400

    def __str__(self) -> str:
        return f"Invalid PROXY line: {self.line!r}"


class ForbiddenProxyRequest(ParseException):
    def __init__(self, host: str):
        self.host = host
        self.code = 403

    def __str__(self) -> str:
        return f"Proxy request from {self.host!r} not allowed"


class InvalidSchemeHeaders(ParseException):
    def __str__(self) -> str:
        return "Contradictory scheme headers"
