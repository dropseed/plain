from __future__ import annotations

import asyncio
import errno
import logging
import ssl
from datetime import datetime
from typing import TYPE_CHECKING, Any

from plain.logs import get_framework_logger

from .. import http
from ..accesslog import log_access
from ..connection import KEEPALIVE, Connection
from .errors import (
    ConfigurationProblem,
    InvalidHeader,
    InvalidHeaderName,
    InvalidHostHeader,
    InvalidHTTPVersion,
    InvalidRequestLine,
    InvalidRequestMethod,
    LimitRequestHeaders,
    LimitRequestLine,
    ObsoleteFolding,
    UnsupportedTransferCoding,
)
from .message import LIMIT_REQUEST_FIELD_SIZE, LIMIT_REQUEST_FIELDS, Request
from .request import create_request
from .response import Response
from .unreader import AsyncBridgeUnreader, BufferUnreader

if TYPE_CHECKING:
    from ..workers.worker import Worker

log = get_framework_logger()

HEALTHCHECK_RESPONSE = (
    b"HTTP/1.1 200 OK\r\n"
    b"Content-Type: text/plain\r\n"
    b"Content-Length: 2\r\n"
    b"Connection: close\r\n"
    b"\r\nok"
)


def extract_request_path(header_data: bytes) -> bytes:
    """Extract the raw path (without query string) from an HTTP/1.x request line.

    Returns an empty bytes object if the request line cannot be parsed.
    """
    request_line_end = header_data.find(b"\r\n")
    if request_line_end <= 0:
        return b""
    parts = header_data[:request_line_end].split(b" ", 2)
    if len(parts) < 2:
        return b""
    return parts[1].split(b"?", 1)[0]


class _ParseError(Exception):
    """Raised for connection-level issues (EOF, disconnect) that don't need an error response."""


class _IncompleteBody(Exception):
    """Raised when the request body could not be fully read (timeout or disconnect)."""


class _BodyTooLarge(Exception):
    """Raised when a chunked body exceeds the pre-buffer limit.

    Carries the partial data so the caller can fall back to bridge mode.
    """

    def __init__(self, partial_data: bytes) -> None:
        self.partial_data = partial_data


# Total time allowed for reading all headers (slowloris protection).
# Individual recv calls use KEEPALIVE as their timeout, but a client
# could send one byte every ~1.9s to stay under the per-recv limit.
# This bounds the total wall-clock time for the header phase.
HEADER_READ_TIMEOUT = 10

# Maximum total size of headers (request line + headers) in bytes.
# This bounds the async read loop to prevent slow/malicious clients
# from consuming unbounded memory.
MAX_HEADER_SIZE = LIMIT_REQUEST_FIELDS * (LIMIT_REQUEST_FIELD_SIZE + 2) + 4


def _is_chunked_complete(data: bytes) -> bool:
    """Check if a chunked transfer-encoded body is complete.

    Properly parses chunk boundaries to avoid false matches in binary data.
    """
    pos = 0
    n = len(data)
    while pos < n:
        # Find \r\n after chunk size
        crlf = data.find(b"\r\n", pos)
        if crlf < 0:
            return False

        # Parse chunk size (hex, ignore extensions after semicolon)
        size_line = data[pos:crlf]
        semi = size_line.find(b";")
        if semi >= 0:
            size_line = size_line[:semi]

        try:
            chunk_size = int(size_line.strip(), 16)
        except ValueError:
            return False

        if chunk_size == 0:
            # Last chunk — need trailing \r\n (no trailers) or trailers + \r\n\r\n
            after_last = crlf + 2
            if after_last >= n:
                return False
            if data[after_last : after_last + 2] == b"\r\n":
                return True
            return data.find(b"\r\n\r\n", after_last) >= 0

        # Skip chunk data + \r\n
        next_pos = crlf + 2 + chunk_size + 2
        if next_pos > n:
            return False
        pos = next_pos

    return False


def _parse_body_headers(header_data: bytes) -> tuple[int, bool, bool]:
    """Extract Content-Length, Transfer-Encoding, and Expect from raw headers.

    Returns (content_length, is_chunked, expect_continue).
    content_length is -1 if not present or invalid.
    """
    content_length = -1
    is_chunked = False
    expect_continue = False

    header_str = header_data.decode("latin-1", errors="replace")
    lines = header_str.split("\r\n")
    for line in lines[1:]:  # skip request line
        if not line:
            break
        if ":" not in line:
            continue
        name, _, value = line.partition(":")
        name_upper = name.strip().upper()
        if name_upper == "CONTENT-LENGTH":
            try:
                content_length = int(value.strip())
            except ValueError:
                content_length = -1
        elif name_upper == "TRANSFER-ENCODING":
            if "chunked" in value.lower():
                is_chunked = True
        elif name_upper == "EXPECT":
            if "100-continue" in value.lower():
                expect_continue = True

    # RFC 9112 §6.1: If both Content-Length and Transfer-Encoding are
    # present, Transfer-Encoding takes precedence. Ignore Content-Length
    # to ensure the body strategy (pre-buffer vs bridge) uses chunked reading.
    if is_chunked and content_length >= 0:
        content_length = -1

    return content_length, is_chunked, expect_continue


async def async_read_headers(
    conn: Connection, log: logging.Logger
) -> tuple[bytes, bytes]:
    """Read from the connection until the header delimiter \\r\\n\\r\\n.

    Returns (header_data, body_start) where body_start contains any
    bytes read past the header boundary.  Returns (b"", b"") on EOF.
    Raises LimitRequestHeaders if headers exceed MAX_HEADER_SIZE.
    Raises TimeoutError if total header read exceeds HEADER_READ_TIMEOUT.
    """
    buf = bytearray()
    # Prepend any byte consumed during keepalive wait
    if conn._keepalive_byte:
        buf.extend(conn._keepalive_byte)
        conn._keepalive_byte = b""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + HEADER_READ_TIMEOUT
    while True:
        remaining = deadline - loop.time()
        if remaining <= 0:
            log.debug(
                "Header read exceeded total timeout",
                extra={"timeout": HEADER_READ_TIMEOUT},
            )
            raise TimeoutError("Header read timeout exceeded")
        try:
            data = await asyncio.wait_for(
                conn.recv(8192),
                timeout=min(KEEPALIVE, remaining),
            )
        except TimeoutError:
            if buf:
                log.debug("Slow client timed out during header read")
            raise
        if not data:
            return b"", b""

        buf.extend(data)

        idx = buf.find(b"\r\n\r\n")
        if idx >= 0:
            header_end = idx + 4
            return bytes(buf[:header_end]), bytes(buf[header_end:])

        if len(buf) > MAX_HEADER_SIZE:
            raise LimitRequestHeaders("Request headers exceeded max size")


async def async_read_body(
    conn: Connection,
    body_start: bytes,
    content_length: int,
    is_chunked: bool,
    max_body: int,
) -> bytes:
    """Pre-buffer the request body from the connection.

    Called for small bodies that fit in max_body. Header analysis and
    100-continue are handled by the caller.
    Returns the full body bytes. Raises _IncompleteBody on failure.
    """
    if content_length == 0 or (content_length < 0 and not is_chunked):
        return b""

    body = bytearray(body_start)

    if content_length > 0:
        remaining = content_length - len(body)
        while remaining > 0:
            try:
                chunk = await asyncio.wait_for(
                    conn.recv(min(remaining, 65536)),
                    timeout=KEEPALIVE,
                )
            except (TimeoutError, OSError):
                raise _IncompleteBody(
                    f"Expected {content_length} bytes, got {len(body)}"
                )
            if not chunk:
                raise _IncompleteBody(
                    f"Expected {content_length} bytes, got {len(body)}"
                )
            body.extend(chunk)
            remaining -= len(chunk)
        return bytes(body)

    if is_chunked:
        return await async_read_chunked_body(conn, body, max_body)

    return bytes(body)


async def async_read_chunked_body(
    conn: Connection,
    initial: bytearray,
    max_body: int,
) -> bytes:
    """Read a chunked transfer-encoded body asynchronously.

    Returns the raw chunked data (including chunk framing). The parser's
    ChunkedReader will decode it properly.
    Raises _IncompleteBody if the chunked message is not complete.
    Raises _BodyTooLarge if the body exceeds max_body (caller should
    fall back to bridge mode).
    """
    buf = initial

    # Check if initial data already contains the complete chunked body
    # (common when the entire request fits in one recv)
    if len(buf) >= 5 and buf[-4:] == b"\r\n\r\n" and _is_chunked_complete(bytes(buf)):
        return bytes(buf)

    complete = False
    while len(buf) <= max_body:
        try:
            chunk = await asyncio.wait_for(
                conn.recv(65536),
                timeout=KEEPALIVE,
            )
        except (TimeoutError, OSError):
            raise _IncompleteBody("Chunked body read timed out or disconnected")
        if not chunk:
            raise _IncompleteBody("Client disconnected during chunked body")
        buf.extend(chunk)

        # Only run the full parse when the buffer could contain the terminator
        if buf[-4:] == b"\r\n\r\n" and _is_chunked_complete(bytes(buf)):
            complete = True
            break

    if not complete:
        raise _BodyTooLarge(bytes(buf))

    return bytes(buf)


def parse_request(
    worker: Worker,
    conn: Connection,
    unreader: BufferUnreader | AsyncBridgeUnreader,
    force_close: bool = False,
) -> tuple[Any, Any, Response, datetime] | None:
    """Parse an HTTP request from an unreader.

    Works with both BufferUnreader (pre-buffered) and AsyncBridgeUnreader
    (lazy streaming for large bodies).

    When force_close=True (bridge path), this runs in the thread pool.
    Body reads via chunk() bridge back to the event loop and are safe here.
    NOTE: Async views that read request.body on the event loop will
    deadlock with bridge connections because chunk() blocks the calling
    thread. This is an acceptable limitation — large uploads (> max_body)
    should use sync views. Increase DATA_UPLOAD_MAX_MEMORY_SIZE to avoid
    the bridge path if async body access is needed.

    Returns (req, http_request, resp, request_start) or None on EOF/close.
    Raises _ParseError for connection-level issues (EOF, disconnect).
    Lets HTTP protocol errors propagate so the caller can send
    async error responses.
    """
    try:
        req = Request(worker.app.is_ssl, unreader, conn.client, conn.req_count + 1)

        if not req:
            return None

        request_start = datetime.now()

        # create_request sets _stream = req.body, which is the parser's
        # body reader — it properly decodes chunked/length-delimited data.
        http_request = create_request(req, conn.client, conn.server)

        resp = Response(req, conn.writer, is_ssl=conn.is_ssl)

        if force_close or not worker.alive:
            resp.force_close()
        elif worker.nr_conns >= worker.max_keepalived:
            resp.force_close()

        return (req, http_request, resp, request_start)
    except http.errors.NoMoreData as e:
        worker.log.debug(
            "Ignored premature client disconnection",
            extra={"error": str(e)},
        )
        raise _ParseError from e
    except StopIteration as e:
        worker.log.debug("Closing connection", extra={"error": str(e)})
        raise _ParseError from e
    except OSError as e:
        if e.errno not in (errno.EPIPE, errno.ECONNRESET, errno.ENOTCONN):
            worker.log.exception("Socket error processing request.")
        else:
            worker.log.debug("Ignoring connection error", extra={"error": str(e)})
        raise _ParseError from e
    # HTTP protocol errors (InvalidRequestLine, InvalidHeader, etc.)
    # propagate to the caller for async error response handling.


async def async_handle_error(
    worker: Worker,
    req: Request | None,
    conn: Connection,
    exc: BaseException,
) -> None:
    """Handle request errors, sending an appropriate HTTP error response."""
    request_start = datetime.now()
    addr = conn.client or ("", -1)  # unix socket case
    if isinstance(
        exc,
        InvalidRequestLine
        | InvalidRequestMethod
        | InvalidHTTPVersion
        | InvalidHeader
        | InvalidHeaderName
        | InvalidHostHeader
        | LimitRequestLine
        | LimitRequestHeaders
        | UnsupportedTransferCoding
        | ConfigurationProblem
        | ObsoleteFolding
        | ssl.SSLError,
    ):
        status_int = 400
        reason = "Bad Request"

        if isinstance(exc, InvalidRequestLine):
            mesg = f"Invalid Request Line '{exc}'"
        elif isinstance(exc, InvalidRequestMethod):
            mesg = f"Invalid Method '{exc}'"
        elif isinstance(exc, InvalidHTTPVersion):
            mesg = f"Invalid HTTP Version '{exc}'"
        elif isinstance(exc, UnsupportedTransferCoding):
            mesg = str(exc)
            status_int = 501
        elif isinstance(exc, ConfigurationProblem):
            mesg = str(exc)
            status_int = 500
        elif isinstance(exc, ObsoleteFolding):
            mesg = str(exc)
        elif isinstance(exc, InvalidHostHeader):
            mesg = str(exc)
        elif isinstance(exc, InvalidHeaderName | InvalidHeader):
            mesg = str(exc)
            if not req and hasattr(exc, "req"):
                req = exc.req  # type: ignore  # for access log
        elif isinstance(exc, LimitRequestLine):
            mesg = str(exc)
        elif isinstance(exc, LimitRequestHeaders):
            reason = "Request Header Fields Too Large"
            mesg = f"Error parsing headers: '{exc}'"
            status_int = 431
        elif isinstance(exc, ssl.SSLError):
            reason = "Forbidden"
            mesg = f"'{exc}'"
            status_int = 403

        worker.log.warning("Invalid request", extra={"ip": addr[0], "error": str(exc)})
    else:
        if hasattr(req, "uri"):
            worker.log.exception("Error handling request", extra={"uri": req.uri})
        else:
            worker.log.exception("Error handling request (no URI read)")
        status_int = 500
        reason = "Internal Server Error"
        mesg = ""

    if req is not None:
        request_time = datetime.now() - request_start
        resp = Response(req, conn.writer, is_ssl=conn.is_ssl)
        resp.status = f"{status_int} {reason}"
        resp.response_length = len(mesg)
        log_access(resp, req, request_time)

    try:
        await conn.write_error(status_int, reason, mesg)
    except Exception:
        worker.log.debug("Failed to send error message.")


async def async_finish_request(
    req: Any,
    resp: Response,
    http_response: Any,
    request_start: datetime,
) -> bool:
    """Write response using async I/O, log access, and determine keepalive."""
    try:
        await resp.async_write_response(http_response)
    finally:
        request_time = datetime.now() - request_start
        if http_response.log_access:
            log_access(resp, req, request_time)
        if hasattr(http_response, "close"):
            http_response.close()

    if resp.should_close():
        log.debug("Closing connection.")
        return False

    return True


async def async_handle_dispatch_error(
    worker: Worker, req: Any, resp: Response, conn: Connection, exc: BaseException
) -> bool:
    """Handle exceptions from dispatch. Returns False (no keepalive)."""
    # TimeoutError is a subclass of OSError but isn't a socket error —
    # it's an app-level timeout (e.g., asyncio.wait_for in a view).
    # Send a 500 response instead of silently dropping the connection.
    if isinstance(exc, TimeoutError):
        if not resp.headers_sent:
            await async_handle_error(worker, req, conn, exc)
        return False

    if isinstance(exc, ConnectionResetError):
        # asyncio's _drain_helper raises ConnectionResetError('Connection lost')
        # without an errno, so we handle it before the errno-based OSError check.
        worker.log.debug(
            "Client disconnected during dispatch",
            extra={"error": str(exc)},
        )
        return False

    if isinstance(exc, OSError):
        if exc.errno in (errno.EPIPE, errno.ECONNRESET, errno.ENOTCONN):
            worker.log.debug(
                "Client disconnected during dispatch",
                extra={"error": str(exc)},
            )
        else:
            worker.log.exception("Socket error during dispatch.")
        return False

    if resp.headers_sent:
        worker.log.exception("Error handling request")
        try:
            conn.close()
        except OSError:
            pass
    else:
        await async_handle_error(worker, req, conn, exc)
    return False


async def dispatch(
    worker: Worker,
    req: Any,
    conn: Connection,
    http_request: Any,
    resp: Response,
    request_start: datetime,
) -> bool:
    """Dispatch a request through the handler and write the response."""
    try:
        http_response = await worker.handler.handle(http_request, worker.tpool)

        # Check for async streaming response (SSE, etc.)
        from plain.http import AsyncStreamingResponse

        if isinstance(http_response, AsyncStreamingResponse):
            return await stream_async_response(req, resp, http_response, request_start)

        # Write response using async I/O (no thread pool needed)
        return await async_finish_request(req, resp, http_response, request_start)
    except Exception as exc:
        return await async_handle_dispatch_error(worker, req, resp, conn, exc)


async def stream_async_response(
    req: Any,
    resp: Response,
    http_response: Any,
    request_start: datetime,
) -> bool:
    """Stream an async response (SSE, etc.) chunk by chunk.

    Headers and chunks are written using async I/O. This keeps the
    event loop free between chunks and doesn't consume thread pool slots.
    """
    client_disconnected = False
    try:
        resp.prepare_response(http_response)
        await resp.async_send_headers()

        async for chunk in http_response:
            try:
                await resp.async_write(chunk)
            except OSError:
                client_disconnected = True
                break
    finally:
        try:
            if hasattr(http_response, "aclose"):
                await http_response.aclose()
        except Exception:
            log.debug("Error in aclose()")

        try:
            if not client_disconnected:
                await resp.async_close()
        except OSError:
            pass
        finally:
            request_time = datetime.now() - request_start
            if http_response.log_access:
                log_access(resp, req, request_time)
            if hasattr(http_response, "close"):
                http_response.close()

    if client_disconnected or resp.should_close():
        return False
    return True


async def handle_connection(worker: Worker, conn: Connection) -> None:
    """HTTP/1.1 keepalive connection loop.

    Reads requests, dispatches them, and loops for keepalive.
    Called after TLS and ALPN detection in Worker._handle_connection.
    """
    loop = asyncio.get_running_loop()

    while worker.alive:
        # Read HTTP headers asynchronously on the event loop
        try:
            header_data, body_start = await async_read_headers(conn, worker.log)
        except (TimeoutError, OSError):
            break
        except LimitRequestHeaders as e:
            await async_handle_error(worker, None, conn, e)
            break
        if not header_data:
            break

        # Health check — respond on the event loop without touching the thread pool.
        if worker.healthcheck_path_bytes:
            path = extract_request_path(header_data)
            if path == worker.healthcheck_path_bytes:
                await conn.sendall(HEALTHCHECK_RESPONSE)
                break

        # Analyze headers to determine body handling strategy
        max_body = worker.max_body
        content_length, is_chunked, expect_continue = _parse_body_headers(header_data)

        if expect_continue:
            try:
                await conn.sendall(b"HTTP/1.1 100 Continue\r\n\r\n")
            except OSError:
                break

        # Large Content-Length bodies use the bridge for lazy streaming.
        # Small bodies and chunked are pre-buffered (with fallback to
        # bridge if a chunked body exceeds the pre-buffer limit).
        use_bridge = content_length > max_body

        if use_bridge:
            unreader = AsyncBridgeUnreader(
                header_data + body_start,
                conn,
                loop,
                timeout=worker.timeout,
            )
        else:
            try:
                body_data = await async_read_body(
                    conn,
                    body_start,
                    content_length,
                    is_chunked,
                    max_body,
                )
            except _IncompleteBody:
                await conn.write_error(
                    408,
                    "Request Timeout",
                    "Incomplete request body",
                )
                break
            except _BodyTooLarge as e:
                # Chunked body exceeded pre-buffer limit — fall back
                # to bridge mode with the partially-read data.
                use_bridge = True
                unreader = AsyncBridgeUnreader(
                    header_data + e.partial_data,
                    conn,
                    loop,
                    timeout=worker.timeout,
                )
            else:
                unreader = BufferUnreader(header_data + body_data)

        # Parse the request. For bridge unreaders, parsing runs in
        # the thread pool since the body reader may call chunk()
        # which bridges back to the event loop.
        try:
            if use_bridge:
                parse_result = await loop.run_in_executor(
                    worker.tpool,
                    parse_request,
                    worker,
                    conn,
                    unreader,
                    True,
                )
            else:
                parse_result = parse_request(worker, conn, unreader)
        except _ParseError:
            break
        except TimeoutError:
            # Bridge body read timed out — send 408 (not 500)
            await conn.write_error(
                408,
                "Request Timeout",
                "Body read timed out",
            )
            break
        except Exception as e:
            await async_handle_error(worker, None, conn, e)
            break

        if parse_result is None:
            break

        req, http_request, resp, request_start = parse_result
        conn.req_count += 1
        worker._count_request()

        keepalive = await dispatch(worker, req, conn, http_request, resp, request_start)

        # For bridge connections with known Content-Length, drain
        # unread body data so the client receives the response
        # without TCP RST. Chunked-to-bridge fallback (content_length=-1)
        # can't drain by length; force_close=True ensures the
        # connection closes cleanly via Connection: close header.
        if use_bridge and content_length > 0:
            remaining = (
                content_length - len(body_start) - unreader.socket_bytes_read  # type: ignore
            )
            while remaining > 0:
                try:
                    data = await asyncio.wait_for(
                        conn.recv(min(remaining, 65536)),
                        timeout=KEEPALIVE,
                    )
                except (TimeoutError, OSError):
                    break
                if not data:
                    break
                remaining -= len(data)

        if not keepalive or not worker.alive:
            break

        # Wait for the next request (keepalive)
        try:
            await asyncio.wait_for(
                conn.wait_readable(),
                timeout=KEEPALIVE,
            )
        except (TimeoutError, OSError):
            break
