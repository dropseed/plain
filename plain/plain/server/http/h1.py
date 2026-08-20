from __future__ import annotations

import asyncio
import errno
import ssl
import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from plain.logs import get_framework_logger

from ..accesslog import log_access
from ..connection import DRAIN_MIN_RECV, RECV_PROGRESS_TIMEOUT, Connection
from .errors import (
    BodyBudgetExceeded,
    ChunkedFramingError,
    ConfigurationProblem,
    InvalidHeader,
    InvalidHeaderName,
    InvalidHostHeader,
    InvalidHTTPVersion,
    InvalidRequestLine,
    InvalidRequestMethod,
    LimitRequestBody,
    LimitRequestHeaders,
    LimitRequestLine,
    ObsoleteFolding,
    ParseException,
    UnsupportedTransferCoding,
)
from .message import LIMIT_REQUEST_FIELD_SIZE, LIMIT_REQUEST_FIELDS, Request
from .request import create_request
from .response import Response
from .sink import BodyRateFloor, BodySink, ChunkedDecoder

if TYPE_CHECKING:
    from ..workers.worker import Worker

log = get_framework_logger()

# Built headers-first from the body literal so the GET and HEAD
# variants can't drift: HEAD is the header block (Content-Length
# describes the GET body — RFC 9110 9.3.2), GET appends the body.
_HEALTHCHECK_BODY = b"ok"
HEALTHCHECK_RESPONSE_HEAD = (
    b"HTTP/1.1 200 OK\r\n"
    b"Content-Type: text/plain\r\n"
    b"Content-Length: " + str(len(_HEALTHCHECK_BODY)).encode() + b"\r\n"
    b"Connection: close\r\n"
    b"\r\n"
)
HEALTHCHECK_RESPONSE = HEALTHCHECK_RESPONSE_HEAD + _HEALTHCHECK_BODY


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


class _IncompleteBody(Exception):
    """Raised when the request body could not be fully read (timeout or disconnect)."""


# Total time allowed for reading all headers (slowloris protection).
# Individual recv calls use RECV_PROGRESS_TIMEOUT as their timeout, but a
# client could send one byte every ~1.9s to stay under the per-recv limit.
# This bounds the total wall-clock time for the header phase.
HEADER_READ_TIMEOUT = 10

# Maximum total size of headers (request line + headers) in bytes.
# This bounds the async read loop to prevent slow/malicious clients
# from consuming unbounded memory.
MAX_HEADER_SIZE = LIMIT_REQUEST_FIELDS * (LIMIT_REQUEST_FIELD_SIZE + 2) + 4

# Lingering-close bounds for a request rejected before its body was read
# (e.g. 413). A client that doesn't use Expect: 100-continue is already
# sending the body, and closing with unread bytes in the socket sends an
# RST that can clobber the error response before the client reads it.
# The linger drains and discards just long enough for the response to
# land; both bounds keep a hostile sender from pinning the connection.
LINGER_CLOSE_TIMEOUT = 3.0
LINGER_CLOSE_MAX_BYTES = 4 * 1024 * 1024


# Per-recv timeout while receiving a request body. Larger than the
# header progress timeout because a large upload legitimately stalls
# between packets (cellular handoff, a TCP RTO after loss) far longer
# than a header block ever should — and slow-drip protection for the
# body phase is the throughput floor (SERVER_BODY_MIN_BYTES_PER_SECOND),
# not this per-recv bound.
BODY_RECV_TIMEOUT = 15.0


def _recv_timeout(worker: Worker, base: float = RECV_PROGRESS_TIMEOUT) -> float:
    """Per-recv timeout: `base`, capped by the worker's drain read
    deadline once shutdown publishes one. Read live on every recv, so a
    SIGTERM landing mid-request bounds that request's remaining reads
    too. Floored at DRAIN_MIN_RECV so a ready request is never dropped by
    a zero timeout; the total is bounded by the deadline checks in the
    read loops themselves.
    """
    deadline = worker.drain_read_deadline
    if deadline is None:
        return base
    return min(base, max(DRAIN_MIN_RECV, deadline - time.monotonic()))


def _drain_expired(worker: Worker) -> bool:
    """True once shutdown's drain read deadline has passed."""
    deadline = worker.drain_read_deadline
    return deadline is not None and time.monotonic() >= deadline


async def _linger_discard(worker: Worker, conn: Connection) -> None:
    """Read and discard incoming bytes briefly before closing.

    See LINGER_CLOSE_TIMEOUT — gives a client that is mid-send a window
    to read an already-written error response instead of an RST.
    """
    deadline = time.monotonic() + LINGER_CLOSE_TIMEOUT
    discarded = 0
    while discarded < LINGER_CLOSE_MAX_BYTES and not _drain_expired(worker):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        try:
            data = await asyncio.wait_for(
                conn.recv(65536),
                timeout=min(remaining, _recv_timeout(worker)),
            )
        except (TimeoutError, OSError):
            break
        if not data:
            break
        discarded += len(data)


async def _wait_for_next_request(
    worker: Worker,
    conn: Connection,
    shutdown_wait: asyncio.Task[bool],
) -> bool:
    """Park on an idle connection until the next request starts.

    Runs before every request, the first on a fresh connection included.
    Returns True when request bytes have arrived (peeked by
    wait_readable, handed back by the next recv calls), False when the
    connection should close — idle timeout, shutdown, EOF, or a socket
    error.

    The idle window is worker.keepalive_timeout — long, so the router is
    always the side that closes an idle pooled connection (see
    SERVER_KEEPALIVE_TIMEOUT in global_settings.py for the full
    rationale). Worker shutdown (shutdown_wait) instead collapses the
    wait to one _recv_timeout grace — the same window every drain read
    gets, so it tightens as a published kill deadline approaches: a
    request already in flight is served (framed Connection: close by
    dispatch), otherwise the connection closes promptly.
    """
    idle_read = asyncio.get_running_loop().create_task(conn.wait_readable())
    try:
        await asyncio.wait(
            (idle_read, shutdown_wait),
            timeout=worker.keepalive_timeout,
            return_when=asyncio.FIRST_COMPLETED,
        )
        if not idle_read.done() and shutdown_wait.done():
            await asyncio.wait((idle_read,), timeout=_recv_timeout(worker))
        return idle_read.done() and idle_read.exception() is None and idle_read.result()
    finally:
        idle_read.cancel()
        if idle_read.done() and not idle_read.cancelled():
            # Retrieve any exception so a connection task cancelled during
            # drain in the same tick idle_read failed (e.g. a client RST)
            # doesn't log "Task exception was never retrieved".
            idle_read.exception()


def _expects_continue(req: Request) -> bool:
    # 100 Continue is an HTTP/1.1 mechanism — RFC 9110 §10.1.1; an
    # HTTP/1.0 client can't parse the interim response and would mis-frame.
    if req.version < (1, 1):
        return False
    for name, value in req.headers:
        # Expect is a comma-separated list (RFC 9110 §10.1.1) — answer
        # 100 Continue when it appears among any other members, or a
        # waiting client sits in silence until the body recv times out.
        if name == "EXPECT" and any(
            member.strip().lower() == "100-continue" for member in value.split(",")
        ):
            return True
    return False


async def async_read_headers(worker: Worker, conn: Connection) -> tuple[bytes, bytes]:
    """Read from the connection until the header delimiter \\r\\n\\r\\n.

    Returns (header_data, body_start) where body_start contains any bytes
    read past the header boundary. Returns (b"", b"") on EOF.
    Raises LimitRequestHeaders if headers exceed MAX_HEADER_SIZE.
    Raises TimeoutError if the header read exceeds HEADER_READ_TIMEOUT
    (or, mid-request, the shutdown drain deadline).
    """
    buf = bytearray()
    scan_from = 0
    header_deadline = time.monotonic() + HEADER_READ_TIMEOUT
    while True:
        # RFC 9112 §2.2: ignore empty line(s) before the request-line —
        # e.g. the stray CRLF some clients send after a POST body, which
        # would otherwise 400 the next request on the connection.
        # Bounded by HEADER_READ_TIMEOUT like any other header bytes.
        while buf.startswith(b"\r\n"):
            del buf[:2]
            scan_from = 0

        # Resume the terminator scan where the last one left off (minus
        # a 3-byte overlap for a split terminator) — rescanning from 0
        # per recv is quadratic, and a byte-drip client could pin the
        # event loop for seconds inside HEADER_READ_TIMEOUT.
        idx = buf.find(b"\r\n\r\n", scan_from)
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

        scan_from = max(0, len(buf) - 3)
        buf.extend(data)


async def async_ingest_body(
    worker: Worker,
    conn: Connection,
    sink: BodySink,
    req: Request,
    body_start: bytes,
    content_length: int | None,
    shutdown_wait: asyncio.Task[bool],
) -> bool:
    """Receive the entire request body into the sink on the event loop.

    content_length is the parsed message's framing: an int for a
    declared length (0 = no body), None for chunked.

    Returns True when bytes beyond this request's body were read — the
    start of a pipelined request. Those bytes are dropped and the caller
    closes the connection so the client retries them on a fresh one; we
    never re-frame another request out of a read-ahead buffer, which
    would make our boundary detection a request splitter.

    Raises LimitRequestBody past the policy cap, BodyBudgetExceeded past
    the worker-wide budget, ChunkedFramingError for malformed chunked
    framing, and _IncompleteBody on timeout, disconnect, a drain
    deadline (a body still trickling at shutdown is abandoned with a 408
    rather than pinning the connection), or a client dripping below the
    body rate floor.
    """
    if content_length == 0:
        # No body (RFC 9112 §6): anything past the headers is a pipelined
        # request — but ignore a stray trailing CRLF (RFC 9112 §2.2
        # tolerance), which shouldn't tear down a reusable connection.
        return bool(body_start.strip(b"\r\n"))

    rate = BodyRateFloor(worker.body_min_rate)
    loop = asyncio.get_running_loop()

    async def recv_more(max_size: int = 65536) -> bytes:
        if _drain_expired(worker):
            raise _IncompleteBody("Request body incomplete at drain deadline")
        # Checked on entry — when more bytes are actually needed — never
        # after a recv, so the recv that completes the body can't 408 a
        # complete-but-slow request (a small body after client
        # think-time, a 100-continue client with a slow producer).
        if rate.violated():
            raise _IncompleteBody("Request body below minimum transfer rate")
        wait_start = time.monotonic()
        # Race the recv against worker shutdown so a body read blocked on
        # a slow client is interrupted promptly when the drain begins —
        # the generous BODY_RECV_TIMEOUT (a large upload legitimately
        # stalls between packets far longer than a header block) would
        # otherwise blow past the drain deadline. Once shutdown fires,
        # the deadline caps how long we wait for the rest.
        recv_task = loop.create_task(conn.recv(max_size))
        try:
            await asyncio.wait(
                (recv_task, shutdown_wait),
                timeout=_recv_timeout(worker, BODY_RECV_TIMEOUT),
                return_when=asyncio.FIRST_COMPLETED,
            )
            if not recv_task.done() and shutdown_wait.done():
                # Shutdown began mid-recv; finish under the (now short)
                # drain-capped budget, shielding the recv from wait_for's
                # cancel so we own its teardown.
                try:
                    await asyncio.wait_for(
                        asyncio.shield(recv_task),
                        timeout=_recv_timeout(worker, BODY_RECV_TIMEOUT),
                    )
                except TimeoutError:
                    pass
            if not recv_task.done():
                recv_task.cancel()
                # The error path reads this connection again
                # (_linger_discard) — wait for the cancelled read to
                # release the StreamReader first. asyncio.wait absorbs
                # the task's CancelledError but still propagates our own.
                await asyncio.wait((recv_task,))
                raise _IncompleteBody("Body read timed out or shutdown")
            chunk = recv_task.result()
        except OSError:
            raise _IncompleteBody("Body read disconnected")
        finally:
            if recv_task.done() and not recv_task.cancelled():
                recv_task.exception()  # retrieve to silence the warning
        if not chunk:
            raise _IncompleteBody("Client disconnected during request body")
        rate.record(waited=time.monotonic() - wait_start, received=len(chunk))
        return chunk

    if content_length is None:
        decoder = ChunkedDecoder()
        data = body_start
        while True:
            if decoded := decoder.feed(data):
                sink.feed(decoded)
            if decoder.finished:
                if decoder.trailers:
                    # Validated like the in-band headers were; a bad
                    # trailer is a protocol error, same as before the
                    # sink (the caller maps it to a 400). The parsed
                    # result is discarded — nothing consumes trailers.
                    req.parse_headers(decoder.trailers)
                return bool(decoder.leftover)
            data = await recv_more()

    sink.feed(body_start[:content_length])
    remaining = content_length - len(body_start)
    while remaining > 0:
        # Bounded recv: bytes past the declared length belong to the
        # NEXT request on this connection — they must stay unread in the
        # socket for the next loop iteration, not be consumed here.
        chunk = await recv_more(min(remaining, 65536))
        sink.feed(chunk)
        remaining -= len(chunk)
    # Bytes past the body are a pipelined request (→ close), but a stray
    # trailing CRLF is RFC 9112 §2.2 tolerance — ignore it, like the
    # bodiless path above, so a client that trails its POST bodies with
    # CRLF still keeps the connection alive.
    return bool(body_start[content_length:].strip(b"\r\n"))


def parse_request(
    worker: Worker,
    conn: Connection,
    header_data: bytes,
) -> tuple[Request, Response, datetime]:
    """Parse an HTTP request from its complete header bytes.

    The body has not been read yet — it is ingested afterwards, based on
    the parsed message's framing (see async_ingest_body). Parsing does
    no I/O; HTTP protocol errors (InvalidRequestLine, InvalidHeader,
    etc.) propagate so the caller can send async error responses.
    """
    req = Request(worker.app.is_ssl, header_data, conn.client, conn.req_count + 1)

    request_start = datetime.now(UTC)

    resp = Response(req, conn.writer, is_ssl=conn.is_ssl)

    # Shutdown is NOT consulted here — dispatch() checks worker.alive
    # right before the response is framed, the one place it can't race.
    if worker.nr_conns >= worker.max_keepalived:
        resp.force_close()

    return (req, resp, request_start)


async def async_handle_error(
    worker: Worker,
    req: Request | None,
    conn: Connection,
    exc: BaseException,
) -> None:
    """Handle request errors, sending an appropriate HTTP error response."""
    request_start = datetime.now(UTC)
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
        | LimitRequestBody
        | BodyBudgetExceeded
        | ChunkedFramingError
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
        elif isinstance(exc, (ObsoleteFolding, InvalidHostHeader)):
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
        elif isinstance(exc, LimitRequestBody):
            reason = "Content Too Large"
            mesg = str(exc)
            status_int = 413
        elif isinstance(exc, BodyBudgetExceeded):
            reason = "Service Unavailable"
            mesg = str(exc)
            status_int = 503
        elif isinstance(exc, ChunkedFramingError):
            mesg = str(exc)
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
        request_time = datetime.now(UTC) - request_start
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
        request_time = datetime.now(UTC) - request_start
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

        # A bodiless response (e.g. HEAD on an SSE view) never consumes
        # the stream — it may not terminate. The finally sends the
        # headers via async_close().
        if not resp.omits_body:
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
            request_time = datetime.now(UTC) - request_start
            if http_response.log_access:
                log_access(resp, req, request_time)
            if hasattr(http_response, "close"):
                http_response.close()

    return not (client_disconnected or resp.should_close())


async def handle_connection(worker: Worker, conn: Connection) -> None:
    """HTTP/1.1 keepalive connection loop.

    Reads requests, dispatches them, and loops for keepalive.
    Called after TLS and ALPN detection in Worker._handle_connection.

    Shutdown invariant: a request that has been (or is being) read is
    always answered, with the close announced on the wire before the
    socket closes — dropping it unread is a Heroku router H13. Shutdown
    is consulted in exactly two places: dispatch(), right before the
    response is framed, and _wait_for_next_request().
    """
    loop = asyncio.get_running_loop()

    # Completed when worker shutdown starts — one task per connection (as
    # h2 does), raced against wait_readable in _wait_for_next_request.
    # Don't "optimize" to one worker-wide task shared across connections:
    # asyncio.wait registers/removes a done-callback per waiter, which is
    # O(connections) on a shared task — strictly worse.
    shutdown_wait = loop.create_task(worker.shutdown_event.wait())

    try:
        while True:
            # Long, shutdown-aware idle wait — first request included.
            if not await _wait_for_next_request(worker, conn, shutdown_wait):
                break

            # Read HTTP headers asynchronously on the event loop. Once
            # shutdown starts, all reads are bounded by the worker's drain
            # read deadline (see _recv_timeout).
            conn.request_is_head = False
            try:
                header_data, body_start = await async_read_headers(worker, conn)
            except (TimeoutError, OSError):
                break
            except LimitRequestHeaders as e:
                await async_handle_error(worker, None, conn, e)
                # The client is mid-send of an oversized header block —
                # closing now would RST-clobber the 431 (see
                # LINGER_CLOSE_TIMEOUT).
                await _linger_discard(worker, conn)
                break
            if not header_data:
                break

            # Latch HEAD-ness from the request line before any parsing —
            # everything written from here on (healthcheck, parse-failure
            # errors, the response itself) consults this one fact.
            conn.request_is_head = header_data.startswith(b"HEAD ")

            # Health check — respond on the event loop without touching the
            # thread pool. Still answered during shutdown drain: the response
            # is Connection: close and new connections are already refused, so
            # it can't keep a load balancer pointed at a dying worker.
            if worker.healthcheck_path_bytes:
                path = extract_request_path(header_data)
                if path == worker.healthcheck_path_bytes:
                    if conn.request_is_head:
                        await conn.sendall(HEALTHCHECK_RESPONSE_HEAD)
                    else:
                        await conn.sendall(HEALTHCHECK_RESPONSE)
                    # Like every other pre-body early exit: closing with
                    # unread bytes in the socket (a healthcheck POST's
                    # body, say) can RST-clobber the response. A checker
                    # that closes after reading ends the linger via EOF.
                    await _linger_discard(worker, conn)
                    break

            # Parse the request from the header bytes alone — the body
            # hasn't been read yet, so framing comes from the parsed
            # message (authoritative), never a header pre-scan. Invalid
            # requests are rejected before their body transfers.
            try:
                req, resp, request_start = parse_request(worker, conn, header_data)
            except Exception as e:
                await async_handle_error(worker, None, conn, e)
                # The client may already be mid-send of the body for the
                # request whose headers were just rejected — linger so
                # the error response isn't RST-clobbered.
                await _linger_discard(worker, conn)
                break

            # Authoritative framing from the parsed message (None =
            # chunked) — the parser already rejected ambiguous framing
            # (duplicate Content-Length, CL+TE conflicts, unsupported
            # codings).
            content_length = req.content_length

            # Reject a declared-too-large body before any of it is read —
            # and before 100-continue below, so the client isn't invited
            # to send a body that is already known to be refused.
            if (
                worker.max_request_body is not None
                and content_length is not None
                and content_length > worker.max_request_body
            ):
                # The request parsed, so pass it along for the access log.
                await async_handle_error(
                    worker,
                    req,
                    conn,
                    LimitRequestBody(content_length, worker.max_request_body),
                )
                # Linger unconditionally: even an Expect: 100-continue
                # client may already be sending (RFC 9110 §10.1.1 allows
                # sending after a short wait, and body bytes can already
                # sit in body_start). A client that stops on the 413 and
                # closes ends the linger immediately via EOF.
                await _linger_discard(worker, conn)
                break

            if _expects_continue(req):
                try:
                    await conn.sendall(b"HTTP/1.1 100 Continue\r\n\r\n")
                except OSError:
                    break

            # Ingest the entire body on the event loop before dispatch:
            # memory up to the spool threshold, an anonymous temp file
            # beyond it, the policy cap and worker-wide budget enforced
            # on received bytes. The request thread is held only for
            # view time, and the connection can keep-alive afterwards
            # because the body was fully consumed off the wire.
            sink = BodySink(
                spool_size=worker.body_max_memory_size,
                max_size=worker.max_request_body,
                budget=worker.body_budget,
            )
            ingest_start = time.monotonic()
            try:
                try:
                    pipelined = await async_ingest_body(
                        worker,
                        conn,
                        sink,
                        req,
                        body_start,
                        content_length,
                        shutdown_wait,
                    )
                except _IncompleteBody:
                    # Best-effort: the most common cause is the client
                    # disconnecting mid-body, so the write itself fails.
                    try:
                        await conn.write_error(
                            408,
                            "Request Timeout",
                            "Incomplete request body",
                        )
                    except OSError:
                        break
                    # A rate-floor violation means the client is still
                    # sending; linger so the 408 isn't RST-clobbered. For
                    # a timeout/disconnect the linger reads EOF and
                    # returns at once, and it's a no-op past the drain
                    # deadline — so it's safe on every _IncompleteBody
                    # cause.
                    await _linger_discard(worker, conn)
                    break
                except (ParseException, OSError) as e:
                    # ParseException covers the body-phase rejections
                    # (413 cap, 503 budget, 400 framing) and every
                    # trailer-validation error parse_headers can raise
                    # (InvalidHeader and its siblings). OSError covers a
                    # spool write failing (e.g. ENOSPC) → 500. All are
                    # mapped and logged by async_handle_error.
                    await async_handle_error(worker, req, conn, e)
                    if isinstance(
                        e,
                        LimitRequestBody
                        | BodyBudgetExceeded
                        | ChunkedFramingError
                        | OSError,
                    ):
                        # The rest of the upload is still inbound; an
                        # immediate close would RST-clobber the error
                        # response. (Trailer errors instead mean the
                        # body already arrived in full — nothing to wait
                        # out.)
                        await _linger_discard(worker, conn)
                    break

                http_request = create_request(
                    req,
                    conn.client,
                    conn.server,
                    stream=sink.finish(),
                    received=sink.received,
                    ingest_seconds=time.monotonic() - ingest_start,
                )
                conn.req_count += 1
                worker._count_request()

                # A pipelined request was buffered behind this one. We
                # don't re-frame it (that would mean trusting our own
                # body-boundary detection as a request splitter — a
                # smuggling surface); close instead, and the client
                # retries it on a fresh connection.
                if pipelined:
                    resp.force_close()

                try:
                    keepalive = await dispatch(
                        worker, req, conn, http_request, resp, request_start
                    )
                except asyncio.CancelledError:
                    # A cancelled dispatch (client RST, shutdown) leaves
                    # its executor thread running — it may still read the
                    # body. Detach so the finally's close() doesn't yank
                    # the file out from under that read; GC reclaims it
                    # when the thread drops its reference.
                    sink.detach()
                    raise
            finally:
                # One close for every exit: releases the body's memory,
                # any spooled disk, and its slice of the worker budget.
                sink.close()

            # See docstring: loop exit follows the response framing (keepalive
            # is Response.framed_close, latched when the headers were written).
            # No worker.alive check here — every shutdown path sets
            # worker.shutdown_event (alive=False implies the event), so
            # the next _wait_for_next_request collapses to the grace
            # window on its own (and grants a response that was framed
            # keep-alive just before shutdown the same grace).
            if not keepalive:
                break

    finally:
        shutdown_wait.cancel()
