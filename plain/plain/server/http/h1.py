from __future__ import annotations

import asyncio
import errno
import ssl
import time
from datetime import datetime
from typing import TYPE_CHECKING, Any

from plain.logs import get_framework_logger

from .. import http
from ..accesslog import log_access
from ..connection import DRAIN_MIN_RECV, KEEPALIVE, Connection
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


def _chunked_end(data: bytes | bytearray, start: int = 0) -> tuple[int, int]:
    """Find where a complete chunked transfer-encoded body ends.

    Parses chunk boundaries from offset `start` (so binary chunk data
    can't false-match a terminator). Returns (end, resume): `end` is the
    offset just past the terminating CRLF — bytes beyond it are a
    pipelined request — or -1 if not yet complete; `resume` is the last
    fully-parsed chunk boundary, pass it back as `start` so the scan
    doesn't re-walk validated chunks on each recv.

    This drives only completion detection and the force_close decision —
    the trailing bytes are dropped, never re-framed as a request, so
    leniency here cannot desync the request boundary (the parser's
    ChunkedReader is the authoritative framing when the body is read).
    """
    pos = start
    n = len(data)
    while pos < n:
        # Find \r\n after chunk size
        crlf = data.find(b"\r\n", pos)
        if crlf < 0:
            return -1, pos

        # Parse chunk size (hex, ignore extensions after semicolon)
        size_line = data[pos:crlf]
        semi = size_line.find(b";")
        if semi >= 0:
            size_line = size_line[:semi]

        try:
            chunk_size = int(size_line.strip(), 16)
        except ValueError:
            return -1, pos
        if chunk_size < 0:
            # int(x, 16) accepts signed values the chunk grammar forbids;
            # advancing by a negative size would move pos backward and spin
            # this scan forever on the event loop.
            return -1, pos

        if chunk_size == 0:
            # Last chunk — need trailing \r\n (no trailers) or trailers + \r\n\r\n
            after_last = crlf + 2
            if after_last >= n:
                return -1, pos
            if data[after_last : after_last + 2] == b"\r\n":
                return after_last + 2, pos
            trailers_end = data.find(b"\r\n\r\n", after_last)
            if trailers_end < 0:
                return -1, pos
            return trailers_end + 4, pos

        # Skip chunk data + \r\n
        next_pos = crlf + 2 + chunk_size + 2
        if next_pos > n:
            return -1, pos
        pos = next_pos

    return -1, pos


def _recv_timeout(worker: Worker) -> float:
    """Per-recv timeout: KEEPALIVE, capped by the worker's drain read
    deadline once shutdown publishes one. Read live on every recv, so a
    SIGTERM landing mid-request bounds that request's remaining reads too.
    Floored at DRAIN_MIN_RECV so a ready request is never dropped by a
    zero timeout; the total is bounded by the deadline checks in the read
    loops themselves.
    """
    deadline = worker.drain_read_deadline
    if deadline is None:
        return KEEPALIVE
    return min(KEEPALIVE, max(DRAIN_MIN_RECV, deadline - time.monotonic()))


def _drain_expired(worker: Worker) -> bool:
    """True once shutdown's drain read deadline has passed."""
    deadline = worker.drain_read_deadline
    return deadline is not None and time.monotonic() >= deadline


def _parse_body_headers(header_data: bytes) -> tuple[int, bool, bool]:
    """Extract Content-Length, Transfer-Encoding, and Expect from raw headers.

    Returns (content_length, is_chunked, expect_continue). content_length
    is -1 if not present or invalid. This only picks the pre-buffer vs
    bridge read strategy — the authoritative body framing (and rejection
    of unsupported/ambiguous Transfer-Encodings) is done by the parser in
    Request.set_body_reader, so a body we misclassify here still can't
    desync the request boundary.
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


async def async_read_headers(worker: Worker, conn: Connection) -> tuple[bytes, bytes]:
    """Read from the connection until the header delimiter \\r\\n\\r\\n.

    Returns (header_data, body_start) where body_start contains any bytes
    read past the header boundary. Returns (b"", b"") on EOF.
    Raises LimitRequestHeaders if headers exceed MAX_HEADER_SIZE.
    Raises TimeoutError if the header read exceeds HEADER_READ_TIMEOUT
    (or, mid-request, the shutdown drain deadline).
    """
    buf = bytearray()
    # Prepend the byte peeked during the keepalive wait, if any.
    if conn._keepalive_byte:
        buf.extend(conn._keepalive_byte)
        conn._keepalive_byte = b""
    header_deadline = time.monotonic() + HEADER_READ_TIMEOUT
    while True:
        idx = buf.find(b"\r\n\r\n")
        if idx >= 0:
            # A complete request is served even if the drain deadline has
            # since passed — the deadline only stops us waiting for more.
            header_end = idx + 4
            return bytes(buf[:header_end]), bytes(buf[header_end:])

        if len(buf) > MAX_HEADER_SIZE:
            raise LimitRequestHeaders("Request headers exceeded max size")

        remaining = header_deadline - time.monotonic()
        if remaining <= 0:
            worker.log.debug(
                "Header read exceeded total timeout",
                extra={"timeout": HEADER_READ_TIMEOUT},
            )
            raise TimeoutError("Header read timeout exceeded")
        # A partially-arrived request past the drain deadline is abandoned
        # rather than waited on (the client will retry on a new
        # connection); a request not yet started keeps the keepalive wait.
        if buf and _drain_expired(worker):
            raise TimeoutError("Drain deadline exceeded during header read")
        try:
            data = await asyncio.wait_for(
                conn.recv(8192),
                timeout=min(remaining, _recv_timeout(worker)),
            )
        except TimeoutError:
            if buf:
                worker.log.debug("Slow client timed out during header read")
            raise
        if not data:
            return b"", b""

        buf.extend(data)


async def async_read_body(
    worker: Worker,
    conn: Connection,
    body_start: bytes,
    content_length: int,
    is_chunked: bool,
) -> tuple[bytes, bool]:
    """Pre-buffer a request body that fits in worker.max_body.

    Header analysis and 100-continue are handled by the caller. Returns
    (body, pipelined). pipelined is True when bytes were read past the end
    of the body — the start of a pipelined request. Those bytes are
    dropped and the caller closes the connection so the client retries
    them on a fresh connection; we never re-frame another request out of
    this buffer, which would make our boundary detection a request
    splitter. Raises _IncompleteBody on failure, _BodyTooLarge if a
    chunked body exceeds max_body (caller falls back to the bridge).
    """
    if content_length == 0 or (content_length < 0 and not is_chunked):
        # No body: anything past the headers is a pipelined request —
        # but ignore a stray trailing CRLF (RFC 9112 §2.2 tolerance),
        # which shouldn't tear down an otherwise reusable connection.
        return b"", bool(body_start.strip(b"\r\n"))

    if content_length > 0:
        buf = bytearray(body_start)
        while len(buf) < content_length:
            # A body still trickling past the drain deadline is abandoned
            # with a 408 rather than pinning the connection for the window.
            if _drain_expired(worker):
                raise _IncompleteBody(
                    f"Expected {content_length} bytes, got {len(buf)}"
                )
            try:
                chunk = await asyncio.wait_for(
                    conn.recv(min(content_length - len(buf), 65536)),
                    timeout=_recv_timeout(worker),
                )
            except (TimeoutError, OSError):
                raise _IncompleteBody(
                    f"Expected {content_length} bytes, got {len(buf)}"
                )
            if not chunk:
                raise _IncompleteBody(
                    f"Expected {content_length} bytes, got {len(buf)}"
                )
            buf.extend(chunk)
        return bytes(buf[:content_length]), len(buf) > content_length

    return await async_read_chunked_body(worker, conn, bytearray(body_start))


async def async_read_chunked_body(
    worker: Worker,
    conn: Connection,
    buf: bytearray,
) -> tuple[bytes, bool]:
    """Pre-buffer a chunked transfer-encoded body into memory.

    Returns (body, pipelined): the raw chunked bytes up to the terminator
    (the parser's ChunkedReader decodes and authoritatively frames them),
    and whether bytes were read past the terminator — a pipelined request,
    which the caller drops and closes on (never re-framed). Raises
    _IncompleteBody if the message never completes, _BodyTooLarge if it
    exceeds worker.max_body (caller falls back to the bridge).
    """
    scan_from = 0
    while True:
        # Resume the scan from the last validated boundary so a large
        # body isn't re-walked on every recv. Detects completion from the
        # parse position, not a buffer suffix, so trailing pipelined bytes
        # (even binary) don't hide the terminator.
        end, scan_from = _chunked_end(buf, scan_from)
        if end >= 0:
            return bytes(buf[:end]), end < len(buf)

        if len(buf) > worker.max_body:
            raise _BodyTooLarge(bytes(buf))

        # A body still trickling past the drain deadline is abandoned with
        # a 408 rather than pinning the connection until _graceful_shutdown
        # cancels the task (which the client would see as an RST).
        if _drain_expired(worker):
            raise _IncompleteBody("Chunked body incomplete at drain deadline")
        try:
            chunk = await asyncio.wait_for(
                conn.recv(65536),
                timeout=_recv_timeout(worker),
            )
        except (TimeoutError, OSError):
            raise _IncompleteBody("Chunked body read timed out or disconnected")
        if not chunk:
            raise _IncompleteBody("Client disconnected during chunked body")
        buf.extend(chunk)


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

        # Shutdown is NOT consulted here — dispatch() checks worker.alive
        # right before the response is framed, the one place it can't race.
        if force_close or worker.nr_conns >= worker.max_keepalived:
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
            reason = "Not Implemented"
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
                req = exc.req  # ty: ignore[invalid-assignment]  # for access log
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

        # The single shutdown consultation: checked after the view ran and
        # before the response is framed, so a response that goes out
        # keep-alive is one the connection loop will actually keep alive
        # (the loop exit follows the framing; see handle_connection).
        if not worker.alive:
            resp.force_close()

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

    Shutdown invariant: the loop exits exactly when a response was framed
    Connection: close — never on worker.alive directly. A request that
    arrived just as shutdown started (e.g. on a router's pooled
    connection) is still read and served, with the close announced on the
    wire before the socket closes; gating the loop on worker.alive
    instead would drop it unread (Heroku router: H13). Shutdown is
    consulted once, in dispatch(), right before the response is framed.
    """
    loop = asyncio.get_running_loop()

    while True:
        # Read HTTP headers asynchronously on the event loop. Once
        # shutdown starts, all reads are bounded by the worker's drain
        # read deadline (see _recv_timeout).
        try:
            header_data, body_start = await async_read_headers(worker, conn)
        except (TimeoutError, OSError):
            break
        except LimitRequestHeaders as e:
            await async_handle_error(worker, None, conn, e)
            break
        if not header_data:
            break

        # Health check — respond on the event loop without touching the
        # thread pool. Still answered during shutdown drain: the response
        # is Connection: close and new connections are already refused, so
        # it can't keep a load balancer pointed at a dying worker.
        if worker.healthcheck_path_bytes:
            path = extract_request_path(header_data)
            if path == worker.healthcheck_path_bytes:
                await conn.sendall(HEALTHCHECK_RESPONSE)
                break

        # Analyze headers to pick the body read strategy.
        max_body = worker.max_body
        content_length, is_chunked, expect_continue = _parse_body_headers(header_data)

        if expect_continue:
            try:
                await conn.sendall(b"HTTP/1.1 100 Continue\r\n\r\n")
            except OSError:
                break

        # Large Content-Length bodies stream lazily through the bridge.
        # Small known-length, bodiless, and chunked bodies pre-buffer here
        # (chunked falls back to the bridge if it exceeds max_body).
        use_bridge = content_length > max_body
        pipelined = False

        if use_bridge:
            unreader = AsyncBridgeUnreader(
                header_data + body_start,
                conn,
                loop,
                timeout=worker.timeout,
                worker=worker,
            )
        else:
            try:
                body_data, pipelined = await async_read_body(
                    worker, conn, body_start, content_length, is_chunked
                )
            except _IncompleteBody:
                await conn.write_error(
                    408,
                    "Request Timeout",
                    "Incomplete request body",
                )
                break
            except _BodyTooLarge as e:
                # Chunked body exceeded the pre-buffer limit — fall back to
                # the bridge with the partial data. Bridge requests are
                # Connection: close, so no pipelining concern.
                use_bridge = True
                unreader = AsyncBridgeUnreader(
                    header_data + e.partial_data,
                    conn,
                    loop,
                    timeout=worker.timeout,
                    worker=worker,
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

        # A pipelined request was buffered behind this one. We don't
        # re-frame it (that would mean trusting our own body-boundary
        # detection as a request splitter — a smuggling surface); close
        # instead, and the client retries it on a fresh connection.
        if pipelined:
            resp.force_close()

        keepalive = await dispatch(worker, req, conn, http_request, resp, request_start)

        # For bridge connections with known Content-Length, drain
        # unread body data so the client receives the response
        # without TCP RST. Chunked-to-bridge fallback (content_length=-1)
        # can't drain by length; force_close=True ensures the
        # connection closes cleanly via Connection: close header.
        if use_bridge and content_length > 0:
            remaining = (
                content_length - len(body_start) - unreader.socket_bytes_read  # ty: ignore[unresolved-attribute]
            )
            while remaining > 0:
                try:
                    data = await asyncio.wait_for(
                        conn.recv(min(remaining, 65536)),
                        # Plain KEEPALIVE, not the drain budget: the
                        # response is already written, and cutting this
                        # short would close an undrained socket — the
                        # client sees an RST clobber that response.
                        timeout=KEEPALIVE,
                    )
                except (TimeoutError, OSError):
                    break
                if not data:
                    break
                remaining -= len(data)

        # See docstring: loop exit follows the response framing (keepalive
        # is Response.framed_close, latched when the headers were written).
        if not keepalive:
            break

        # Don't solicit another request once shutdown has started. Normal
        # responses already framed close (dispatch force_closes when not
        # alive), but a response whose headers were framed keep-alive
        # before shutdown (e.g. a long streaming response) would otherwise
        # linger idle in the keepalive wait for the whole KEEPALIVE window.
        if not worker.alive:
            break

        # Wait for the next request on the keepalive connection.
        try:
            await asyncio.wait_for(
                conn.wait_readable(),
                timeout=KEEPALIVE,
            )
        except (TimeoutError, OSError):
            break
