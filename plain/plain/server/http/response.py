from __future__ import annotations

#
#
# This file is part of gunicorn released under the MIT license.
# See the LICENSE for more information.
#
# Vendored and modified for Plain.
import asyncio
import logging
import re
from typing import TYPE_CHECKING, Any

from plain.http import FileResponse
from plain.http.response import (
    content_length_forbidden,
    response_omits_body,
    status_omits_body,
)

from .. import util
from .errors import InvalidHeader, InvalidHeaderName
from .message import TOKEN_RE

if TYPE_CHECKING:
    from .message import Request as ServerRequest

# RFC9110 5.5: field-vchar = VCHAR / obs-text
# RFC4234 B.1: VCHAR = 0x21-x07E = printable ASCII
HEADER_VALUE_RE = re.compile(r"[ \t\x21-\x7e\x80-\xff]*")

log = logging.getLogger(__name__)


def warn_dropped_body(
    http_response: Any, *, method: str | None, status_code: int | None
) -> None:
    """Warn when an app-supplied body is dropped for a bodiless status.

    HEAD is silent — a body there is correct app behavior (HEAD == GET
    without the body). Streaming bodies are never consumed, so they
    can't be inspected. Response construction rejects these outright;
    this only fires when status_code was mutated afterwards.
    """
    if method == "HEAD" or not status_omits_body(status_code):
        return
    if http_response.streaming or not http_response.content:
        return
    log.warning(
        "Response body dropped for bodiless status",
        extra={"status": status_code, "method": method},
    )


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


class Response:
    def __init__(
        self,
        req: ServerRequest,
        writer: asyncio.StreamWriter,
        *,
        is_ssl: bool = False,
    ) -> None:
        self.req = req
        self._writer = writer
        self.is_ssl = is_ssl
        self.version = "plain"
        self.status: str | None = None
        self.chunked = False
        self.must_close = False
        # Latched when headers are framed: what the Connection header
        # actually said. Set in default_headers().
        self.framed_close: bool | None = None
        self.headers: list[tuple[str, str]] = []
        self.headers_sent = False
        self.response_length: int | None = None
        self.sent = 0
        self.upgrade = False
        self.status_code: int | None = None

    @property
    def omits_body(self) -> bool:
        """True when this response sends only headers: a HEAD request,
        or a bodiless status (1xx/204/304)."""
        return response_omits_body(self.req.method, self.status_code)

    def force_close(self) -> None:
        self.must_close = True

    def should_close(self) -> bool:
        # Once headers are framed, the wire is the answer — the keepalive
        # decision after the response is written must match what the
        # client was told, or the socket closes on a client that was just
        # promised keep-alive (a dropped request when it pipelines/reuses).
        if self.framed_close is not None:
            return self.framed_close
        if self.must_close or self.req.should_close():
            return True
        if self.response_length is not None or self.chunked:
            return False
        if self.req.method == "HEAD":
            return False
        if self.status_code is None:
            return True
        return not self.omits_body

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
                if content_length_forbidden(self.status_code):
                    continue
                self.response_length = int(value)
            elif util.is_hoppish(name):
                if lname == "connection":
                    # handle websocket
                    if value.lower() == "upgrade":
                        self.upgrade = True
                # Not collapsible: a non-websocket Upgrade must still hit
                # the hop-by-hop `continue` below.
                elif lname == "upgrade":  # noqa: SIM102
                    if value.lower() == "websocket":
                        self.headers.append((name, value))

                # ignore hopbyhop headers
                continue
            self.headers.append((name, value))

    def is_chunked(self) -> bool:
        # Only use chunked responses when the client is
        # speaking HTTP/1.1 or newer and there was
        # no Content-Length header set.
        if self.response_length is not None or self.req.version <= (1, 0):
            return False
        # HEAD, 1xx, 204, and 304 responses have no body to frame.
        return not self.omits_body

    def default_headers(self) -> list[str]:
        # Set the connection header and latch the close decision. The
        # latch records the decision, not the header text: an upgrade
        # response frames "Connection: upgrade" but the keepalive loop
        # still follows should_close() — otherwise force_close() (e.g.
        # shutdown) would be silently ignored on upgrade responses.
        close = self.should_close()
        if self.upgrade:
            connection = "upgrade"
        elif close:
            connection = "close"
        else:
            connection = "keep-alive"

        self.framed_close = close

        headers = [
            f"HTTP/{self.req.version[0]}.{self.req.version[1]} {self.status}\r\n",
            f"Server: {self.version}\r\n",
            f"Date: {util.http_date()}\r\n",
            f"Connection: {connection}\r\n",
        ]
        if self.chunked:
            headers.append("Transfer-Encoding: chunked\r\n")
        return headers

    def prepare_response(self, http_response: Any) -> None:
        """Set status and headers from a plain.http.Response without writing body.

        After calling this, use async_write() to send body chunks and async_close() to finish.
        """
        status = f"{http_response.status_code} {http_response.reason_phrase}"
        response_headers = [
            *((k, v) for k, v in http_response.headers.items() if v is not None),
            *(
                ("Set-Cookie", c.output(header=""))
                for c in http_response.cookies.values()
            ),
        ]
        self.set_status_and_headers(status, response_headers)

    # ------------------------------------------------------------------
    # Async write methods — use asyncio StreamWriter for all I/O.
    # ------------------------------------------------------------------

    async def _async_send(self, data: bytes) -> None:
        """Send bytes using the writer (asyncio streams)."""
        self._writer.write(data)
        await self._writer.drain()

    async def async_send_headers(self) -> None:
        if self.headers_sent:
            return
        tosend = self.default_headers()
        tosend.extend([f"{k}: {v}\r\n" for k, v in self.headers])
        header_str = "{}\r\n".format("".join(tosend))
        await self._async_send(util.to_bytestring(header_str, "latin-1"))
        self.headers_sent = True

    async def async_write(self, arg: bytes) -> None:
        await self.async_send_headers()
        if not isinstance(arg, bytes):
            raise TypeError(f"{arg!r} is not a byte")
        if self.omits_body:
            # Backstop: the write paths skip body iteration for bodiless
            # responses before reaching here — see async_write_response.
            return
        arglen = len(arg)
        tosend = arglen
        if self.response_length is not None:
            if self.sent >= self.response_length:
                return
            tosend = min(self.response_length - self.sent, tosend)
            if tosend < arglen:
                arg = arg[:tosend]

        if self.chunked and tosend == 0:
            return

        self.sent += tosend
        if self.chunked:
            chunk_size = f"{len(arg):X}\r\n"
            chunk = b"".join([chunk_size.encode("utf-8"), arg, b"\r\n"])
            await self._async_send(chunk)
        else:
            await self._async_send(arg)

    async def async_write_response(self, http_response: Any) -> None:
        """Write a plain.http.Response using async I/O."""
        self.prepare_response(http_response)

        if self.omits_body:
            # Headers only (HEAD keeps its Content-Length) — the body is
            # never read or written.
            warn_dropped_body(
                http_response, method=self.req.method, status_code=self.status_code
            )
            await self.async_close()
            return

        if (
            isinstance(http_response, FileResponse)
            and http_response.file_to_stream is not None
        ):
            file_wrapper = FileWrapper(
                http_response.file_to_stream, http_response.block_size
            )
            http_response.file_to_stream.close = http_response.close
            # Read file chunks in the default executor (not the app thread pool)
            # to avoid blocking the event loop. File reads are fast and shouldn't
            # contend with app threads.
            loop = asyncio.get_running_loop()
            while True:
                chunk = await loop.run_in_executor(
                    None, file_wrapper.filelike.read, file_wrapper.blksize
                )
                if not chunk:
                    break
                await self.async_write(chunk)
        else:
            for chunk in http_response:
                await self.async_write(chunk)

        await self.async_close()

    async def async_close(self) -> None:
        if not self.headers_sent:
            await self.async_send_headers()
        if self.chunked:
            await self._async_send(b"0\r\n\r\n")
