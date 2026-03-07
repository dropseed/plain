from __future__ import annotations

import asyncio
import io
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Any

import h2.config
import h2.connection
import h2.events
import h2.exceptions
import h2.settings

from plain.http import AsyncStreamingResponse, FileResponse, StreamingResponse
from plain.http import Request as HttpRequest

from ..accesslog import log_access
from ..util import http_date
from .request import _merge_headers, _resolve_path, _resolve_remote_addr
from .response import FileWrapper

log = logging.getLogger("plain.server")

# Fallback max request body size per H2 stream when DATA_UPLOAD_MAX_MEMORY_SIZE is None (10 MiB)
_H2_BODY_FALLBACK = 10 * 1024 * 1024

# Idle timeout for HTTP/2 connections with no active streams (seconds).
# Browsers typically keep connections open for 5-10 minutes.
H2_IDLE_TIMEOUT = 300

# HTTP/1.1 hop-by-hop headers that must not appear in HTTP/2 responses
_H2_SKIP_HEADERS = frozenset(
    ("connection", "transfer-encoding", "keep-alive", "upgrade")
)


class H2Stream:
    """Accumulates headers and data for a single HTTP/2 stream."""

    __slots__ = ("stream_id", "headers", "data", "data_size")

    def __init__(self, stream_id: int) -> None:
        self.stream_id = stream_id
        self.headers: list[tuple[str, str]] = []
        self.data = io.BytesIO()
        self.data_size = 0


class H2Request:
    """Adapter that looks like the HTTP/1.x parsed request for access logging."""

    def __init__(
        self,
        *,
        method: str,
        path: str,
        query: str,
        headers: list[tuple[str, str]],
        peer_addr: tuple[str, int] | Any,
        scheme: str,
    ) -> None:
        self.method = method
        self.path = path
        self.uri = path + ("?" + query if query else "")
        self.query = query
        self.headers = headers
        self.peer_addr = peer_addr
        self.version = (2, 0)
        self.scheme = scheme

    def should_close(self) -> bool:
        return False


class H2Response:
    """Tracks status/size for access logging of an HTTP/2 response."""

    def __init__(self) -> None:
        self.status: str | None = None
        self.sent: int = 0
        self.response_length: int | None = None
        self.headers_sent: bool = False


def _reject_h2_stream(
    conn: h2.connection.H2Connection,
    state: H2ConnectionState,
    event: h2.events.DataReceived,
    stream: H2Stream,
    status_code: int,
) -> None:
    """Reject an H2 stream with an error response and clean up state."""
    body = f"<h1>{status_code}</h1>".encode()
    try:
        conn.send_headers(
            event.stream_id,
            [
                (":status", str(status_code)),
                ("content-type", "text/html"),
                ("content-length", str(len(body))),
            ],
        )
        conn.send_data(event.stream_id, body, end_stream=True)
    except h2.exceptions.ProtocolError:
        try:
            conn.reset_stream(event.stream_id)
        except h2.exceptions.ProtocolError:
            pass
    conn.acknowledge_received_data(event.flow_controlled_length, event.stream_id)
    state.aggregate_body_size -= stream.data_size
    state.streams.pop(event.stream_id, None)


def _extract_headers_from_stream(
    stream: H2Stream, scheme: str
) -> tuple[str, str, str, str, list[tuple[str, str]]]:
    """Extract method, path, authority, scheme, and regular headers from an H2Stream."""
    method = "GET"
    path = "/"
    authority = ""
    raw_headers: list[tuple[str, str]] = []

    for name, value in stream.headers:
        if name == ":method":
            method = value
        elif name == ":path":
            path = value
        elif name == ":authority":
            authority = value
        elif name == ":scheme":
            scheme = value
        elif not name.startswith(":"):
            raw_headers.append((name.upper(), value))

    if authority and not any(n == "HOST" for n, _ in raw_headers):
        raw_headers.append(("HOST", authority))

    return method, path, authority, scheme, raw_headers


def _resolve_h2_server_address(
    server: tuple[str, int] | Any,
    authority: str,
    scheme: str,
) -> tuple[str, str]:
    """Resolve server name and port for an HTTP/2 connection."""
    if isinstance(server, tuple):
        return str(server[0]), str(server[1])
    if authority:
        parts = authority.rsplit(":", 1)
        port = parts[1] if len(parts) > 1 else ("443" if scheme == "https" else "80")
        return parts[0], port
    return "localhost", "443" if scheme == "https" else "80"


def _build_http_request(
    method: str,
    raw_path: str,
    query: str,
    scheme: str,
    raw_headers: list[tuple[str, str]],
    authority: str,
    client: tuple[str, int] | Any,
    server: tuple[str, int] | Any,
) -> HttpRequest:
    """Build a plain.http.Request from extracted H2 stream data."""
    headers_dict = _merge_headers(raw_headers)
    remote_addr = _resolve_remote_addr(client)
    server_name, server_port = _resolve_h2_server_address(server, authority, scheme)
    path, path_info = _resolve_path(raw_path)

    return HttpRequest(
        method=method,
        path=path,
        headers=headers_dict,
        query_string=query,
        server_scheme=scheme,
        server_name=server_name,
        server_port=server_port,
        remote_addr=remote_addr,
        path_info=path_info,
    )


def _prepare_stream_request(
    stream: H2Stream,
    client: tuple[str, int] | Any,
    server: tuple[str, int] | Any,
    scheme: str,
) -> tuple[H2Request, HttpRequest, H2Response]:
    """Build logging and HTTP request objects from a completed H2 stream."""
    method, raw_path, authority, scheme, raw_headers = _extract_headers_from_stream(
        stream, scheme
    )

    query = ""
    if "?" in raw_path:
        raw_path, query = raw_path.split("?", 1)

    http_request = _build_http_request(
        method, raw_path, query, scheme, raw_headers, authority, client, server
    )

    h2_req = H2Request(
        method=method,
        path=http_request.path_info,
        query=query,
        headers=raw_headers,
        peer_addr=client,
        scheme=scheme,
    )

    stream.data.seek(0)
    http_request._stream = stream.data
    http_request._read_started = False

    return h2_req, http_request, H2Response()


def _build_h2_response_headers(http_response: Any) -> list[tuple[str, str]]:
    """Build HTTP/2 response headers from an http_response."""
    response_headers: list[tuple[str, str]] = [
        (":status", str(http_response.status_code)),
        ("server", "plain"),
        ("date", http_date()),
    ]

    for key, value in http_response.headers.items():
        if value is None:
            continue
        lkey = key.lower()
        if lkey in _H2_SKIP_HEADERS:
            continue
        # RFC 9113 §8.2.2: TE header is only valid with value "trailers"
        if lkey == "te" and value.strip().lower() != "trailers":
            continue
        response_headers.append((lkey, value))

    for cookie in http_response.cookies.values():
        response_headers.append(("set-cookie", cookie.output(header="").strip()))

    return response_headers


class H2ConnectionState:
    """State for an async HTTP/2 connection."""

    def __init__(
        self,
        conn: h2.connection.H2Connection,
        writer: asyncio.StreamWriter,
        client: tuple[str, int] | Any,
        server: tuple[str, int] | Any,
        handler: Any,
        scheme: str,
        executor: ThreadPoolExecutor,
        *,
        stream_budget: asyncio.Semaphore | None = None,
        max_aggregate_body: int = 0,
    ) -> None:
        self.conn = conn
        self.writer = writer
        self.client = client
        self.server = server
        self.handler = handler
        self.scheme = scheme
        self.executor = executor
        self.write_lock = asyncio.Lock()
        self.streams: dict[int, H2Stream] = {}
        self.reset_streams: set[int] = set()
        self.window_events: dict[int, asyncio.Event] = {}
        self.stream_budget = stream_budget
        self.aggregate_body_size: int = 0
        self.max_aggregate_body = max_aggregate_body

    def get_window_event(self, stream_id: int) -> asyncio.Event:
        ev = self.window_events.get(stream_id)
        if ev is None:
            ev = asyncio.Event()
            self.window_events[stream_id] = ev
        return ev

    async def flush(self) -> None:
        """Send any pending h2 data via the asyncio stream writer."""
        outgoing = self.conn.data_to_send()
        if outgoing:
            self.writer.write(outgoing)
            await self.writer.drain()

    def cleanup_stream(self, stream_id: int) -> None:
        """Remove per-stream state after a stream task completes."""
        self.reset_streams.discard(stream_id)
        self.window_events.pop(stream_id, None)


async def async_handle_h2_connection(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    client: tuple[str, int] | Any,
    server: tuple[str, int] | Any,
    handler: Any,
    is_ssl: bool,
    executor: ThreadPoolExecutor,
    stream_budget: asyncio.Semaphore | None = None,
) -> None:
    """Async HTTP/2 connection loop.

    Reads frames from the asyncio StreamReader and dispatches each completed
    stream as an independent asyncio task. All I/O goes through asyncio's
    transport layer (memory BIO for TLS), eliminating the need for a
    dedicated reader thread.
    """
    config = h2.config.H2Configuration(client_side=False)
    conn = h2.connection.H2Connection(config=config)
    conn.initiate_connection()

    from plain.runtime import settings

    # Configure max concurrent streams if set
    max_streams = getattr(settings, "SERVER_H2_MAX_CONCURRENT_STREAMS", None)
    if max_streams:
        conn.update_settings(
            {
                h2.settings.SettingCodes.MAX_CONCURRENT_STREAMS: max_streams,
            }
        )

    scheme = "https" if is_ssl else "http"
    max_body = settings.DATA_UPLOAD_MAX_MEMORY_SIZE or _H2_BODY_FALLBACK
    state = H2ConnectionState(
        conn,
        writer,
        client,
        server,
        handler,
        scheme,
        executor,
        stream_budget=stream_budget,
        max_aggregate_body=max_body * 10,
    )

    stream_tasks: dict[int, asyncio.Task[None]] = {}

    try:
        # Send connection preface
        async with state.write_lock:
            await state.flush()

        while True:
            try:
                data = await asyncio.wait_for(
                    reader.read(65535),
                    timeout=H2_IDLE_TIMEOUT,
                )
            except TimeoutError:
                log.debug("HTTP/2 idle timeout from %s", client)
                break
            if not data:
                break

            h2_events = conn.receive_data(data)

            for event in h2_events:
                if isinstance(event, h2.events.RequestReceived):
                    stream = H2Stream(event.stream_id)
                    stream.headers = [
                        (
                            n.decode("utf-8", errors="surrogateescape")
                            if isinstance(n, bytes)
                            else n,
                            v.decode("utf-8", errors="surrogateescape")
                            if isinstance(v, bytes)
                            else v,
                        )
                        for n, v in event.headers
                    ]
                    state.streams[event.stream_id] = stream

                elif isinstance(event, h2.events.DataReceived):
                    stream = state.streams.get(event.stream_id)
                    data_len = len(event.data)
                    if stream is None:
                        # Stream already rejected/completed — still acknowledge
                        # the data to avoid leaking the connection flow-control window.
                        conn.acknowledge_received_data(
                            event.flow_controlled_length, event.stream_id
                        )
                    elif (
                        state.max_aggregate_body > 0
                        and state.aggregate_body_size + data_len
                        > state.max_aggregate_body
                    ):
                        _reject_h2_stream(conn, state, event, stream, 503)
                        log.warning(
                            "H2 aggregate body budget exceeded on stream %d",
                            event.stream_id,
                        )
                    elif stream.data_size + data_len > max_body:
                        _reject_h2_stream(conn, state, event, stream, 413)
                        log.warning(
                            "H2 stream %d exceeded max body size (%d bytes)",
                            event.stream_id,
                            max_body,
                        )
                    else:
                        stream.data_size += data_len
                        state.aggregate_body_size += data_len
                        stream.data.write(event.data)
                        conn.acknowledge_received_data(
                            event.flow_controlled_length, event.stream_id
                        )

                elif isinstance(event, h2.events.StreamEnded):
                    stream = state.streams.pop(event.stream_id, None)
                    if stream is not None:
                        task = asyncio.get_running_loop().create_task(
                            _async_handle_stream(state, stream)
                        )
                        stream_tasks[event.stream_id] = task

                        def _on_stream_done(
                            t: asyncio.Task[None], sid: int = event.stream_id
                        ) -> None:
                            stream_tasks.pop(sid, None)
                            state.cleanup_stream(sid)

                        task.add_done_callback(_on_stream_done)

                elif isinstance(event, h2.events.StreamReset):
                    stream = state.streams.pop(event.stream_id, None)
                    if stream is not None:
                        state.aggregate_body_size -= stream.data_size
                    state.reset_streams.add(event.stream_id)
                    task = stream_tasks.pop(event.stream_id, None)
                    if task is not None:
                        task.cancel()
                    else:
                        state.cleanup_stream(event.stream_id)

                elif isinstance(event, h2.events.WindowUpdated):
                    ev = state.window_events.get(event.stream_id)
                    if ev is not None:
                        ev.set()
                    if event.stream_id == 0:
                        for ev in state.window_events.values():
                            ev.set()

                elif isinstance(event, h2.events.PriorityUpdated):
                    pass

                elif isinstance(event, h2.events.ConnectionTerminated):
                    async with state.write_lock:
                        await state.flush()
                    break

            else:
                async with state.write_lock:
                    await state.flush()
                continue
            # break from for-loop reached — exit while-loop too
            break

    except h2.exceptions.ProtocolError:
        log.debug("HTTP/2 protocol error on connection from %s", client)
        try:
            async with state.write_lock:
                await state.flush()
        except OSError:
            pass
    except OSError:
        log.debug("HTTP/2 connection closed from %s", client)
    except Exception:
        log.exception("Unexpected error in HTTP/2 connection from %s", client)
    finally:
        for task in stream_tasks.values():
            task.cancel()
        if stream_tasks:
            await asyncio.gather(*stream_tasks.values(), return_exceptions=True)

        try:
            conn.close_connection()
            goaway_data = conn.data_to_send()
            if goaway_data:
                writer.write(goaway_data)
                await writer.drain()
        except Exception:
            pass

        # Close the connection — writer.close() sends TLS close_notify
        # and closes the underlying transport.
        if not writer.is_closing():
            writer.close()
            try:
                await writer.wait_closed()
            except OSError:
                pass


async def _async_handle_stream(
    state: H2ConnectionState,
    stream: H2Stream,
) -> None:
    """Process a single completed HTTP/2 stream as an async task."""
    budget = state.stream_budget
    acquired = False
    try:
        if budget is not None:
            await budget.acquire()
            acquired = True
        await _async_handle_stream_inner(state, stream)
    finally:
        # Always release aggregate body budget — it was incremented in
        # DataReceived before this task was created.
        state.aggregate_body_size -= stream.data_size
        if acquired and budget is not None:
            budget.release()


async def _async_handle_stream_inner(
    state: H2ConnectionState,
    stream: H2Stream,
) -> None:
    """Inner stream handler — budget acquire/release is in the caller."""
    request_start = datetime.now()

    try:
        h2_req, http_request, h2_resp = _prepare_stream_request(
            stream, state.client, state.server, state.scheme
        )
    except Exception:
        log.exception("Error building HTTP/2 request for stream %d", stream.stream_id)
        await _async_send_h2_error(state, stream.stream_id, 500)
        return

    try:
        http_response = await state.handler.handle(http_request, state.executor)

        try:
            if stream.stream_id in state.reset_streams:
                return

            await _async_write_h2_response(
                state, stream.stream_id, http_response, h2_resp
            )
        finally:
            request_time = datetime.now() - request_start
            if http_response.log_access:
                log_access(h2_resp, h2_req, request_time)
            if isinstance(http_response, AsyncStreamingResponse):
                await http_response.aclose()
            if hasattr(http_response, "close"):
                http_response.close()

    except asyncio.CancelledError:
        raise
    except h2.exceptions.StreamClosedError:
        pass
    except Exception:
        log.exception("Error handling HTTP/2 request %s", http_request.path_info)
        if stream.stream_id not in state.reset_streams:
            if h2_resp.headers_sent:
                # Headers already sent — can't send a clean error response.
                # Reset the stream so the client doesn't hang.
                async with state.write_lock:
                    try:
                        state.conn.reset_stream(stream.stream_id)
                        await state.flush()
                    except Exception:
                        pass
            else:
                await _async_send_h2_error(state, stream.stream_id, 500)


async def _async_write_h2_response(
    state: H2ConnectionState,
    stream_id: int,
    http_response: Any,
    h2_resp: H2Response,
) -> None:
    """Write a plain.http response as HTTP/2 frames."""
    loop = asyncio.get_running_loop()
    conn = state.conn
    executor = state.executor
    status_code = http_response.status_code
    h2_resp.status = f"{status_code} {http_response.reason_phrase}"

    response_headers = _build_h2_response_headers(http_response)

    # Async streaming (SSE, etc.) — iterate on event loop
    if isinstance(http_response, AsyncStreamingResponse):
        async with state.write_lock:
            conn.send_headers(stream_id, response_headers)
            await state.flush()
            h2_resp.headers_sent = True

        async for chunk in http_response:
            if chunk:
                h2_resp.sent += len(chunk)
                await _async_send_h2_data(state, stream_id, chunk, end_stream=False)

        async with state.write_lock:
            conn.send_data(stream_id, b"", end_stream=True)
            await state.flush()
        return

    is_file = (
        isinstance(http_response, FileResponse)
        and http_response.file_to_stream is not None
    )

    # Stream response when it's a file, streaming response, or has a
    # declared Content-Length. Only buffer via _collect_body when the
    # response size is unknown (no Content-Length).
    has_content_length = any(n == "content-length" for n, _ in response_headers)

    if is_file or isinstance(http_response, StreamingResponse) or has_content_length:
        if is_file:
            file_wrapper = FileWrapper(
                http_response.file_to_stream, http_response.block_size
            )
            response_iter = iter(file_wrapper)
        else:
            response_iter = iter(http_response)

        async with state.write_lock:
            conn.send_headers(stream_id, response_headers)
            await state.flush()
            h2_resp.headers_sent = True

        while True:
            chunk = await loop.run_in_executor(executor, next, response_iter, None)
            if chunk is None:
                break
            if chunk:
                h2_resp.sent += len(chunk)
                await _async_send_h2_data(state, stream_id, chunk, end_stream=False)

        h2_resp.response_length = h2_resp.sent

        async with state.write_lock:
            conn.send_data(stream_id, b"", end_stream=True)
            await state.flush()
    else:

        def _collect_body() -> bytes:
            parts: list[bytes] = []
            for chunk in http_response:
                if chunk:
                    parts.append(chunk)
            return b"".join(parts)

        body = await loop.run_in_executor(executor, _collect_body)

        if body:
            response_headers.append(("content-length", str(len(body))))

        h2_resp.sent = len(body)
        h2_resp.response_length = len(body)

        if body:
            async with state.write_lock:
                conn.send_headers(stream_id, response_headers)
                await state.flush()
                h2_resp.headers_sent = True
            await _async_send_h2_data(state, stream_id, body, end_stream=True)
        else:
            async with state.write_lock:
                conn.send_headers(stream_id, response_headers, end_stream=True)
                await state.flush()
                h2_resp.headers_sent = True


async def _async_send_h2_data(
    state: H2ConnectionState,
    stream_id: int,
    data: bytes,
    *,
    end_stream: bool = False,
) -> None:
    """Send data respecting HTTP/2 flow control."""
    conn = state.conn
    offset = 0

    stream_event = state.get_window_event(stream_id)
    conn_event = state.get_window_event(0)

    while offset < len(data):
        stream_event.clear()
        conn_event.clear()

        async with state.write_lock:
            max_size = conn.local_flow_control_window(stream_id)
            if max_size > 0:
                chunk_size = min(
                    max_size, len(data) - offset, conn.max_outbound_frame_size
                )
                chunk = data[offset : offset + chunk_size]
                is_last = (offset + chunk_size >= len(data)) and end_stream
                conn.send_data(stream_id, chunk, end_stream=is_last)
                await state.flush()
                offset += chunk_size
                continue

            await state.flush()

        stream_waiter = asyncio.create_task(stream_event.wait())
        conn_waiter = asyncio.create_task(conn_event.wait())
        try:
            done, pending = await asyncio.wait(
                [stream_waiter, conn_waiter],
                timeout=5.0,
                return_when=asyncio.FIRST_COMPLETED,
            )
        except asyncio.CancelledError:
            stream_waiter.cancel()
            conn_waiter.cancel()
            await asyncio.gather(stream_waiter, conn_waiter, return_exceptions=True)
            raise
        for p in pending:
            p.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

        if not done:
            log.warning(
                "H2 stream %d: timed out waiting for flow-control window update, "
                "resetting stream",
                stream_id,
            )
            async with state.write_lock:
                try:
                    conn.reset_stream(stream_id)
                    await state.flush()
                except Exception:
                    pass
            return

    if end_stream and offset == 0:
        async with state.write_lock:
            conn.send_data(stream_id, b"", end_stream=True)
            await state.flush()


async def _async_send_h2_error(
    state: H2ConnectionState,
    stream_id: int,
    status_code: int,
) -> None:
    """Send a simple error response on an HTTP/2 stream."""
    try:
        body = f"<h1>{status_code}</h1>".encode()
        headers = [
            (":status", str(status_code)),
            ("content-type", "text/html"),
            ("content-length", str(len(body))),
        ]
        async with state.write_lock:
            state.conn.send_headers(stream_id, headers)
            state.conn.send_data(stream_id, body, end_stream=True)
            await state.flush()
    except Exception:
        log.debug("Failed to send H2 error response for stream %d", stream_id)
