from __future__ import annotations

import asyncio
import io
import logging
import os
import socket
import threading  # for reader thread only
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Any
from urllib.parse import unquote_to_bytes

import h2.config
import h2.connection
import h2.events
import h2.exceptions

from plain import signals
from plain.http import AsyncStreamingResponse, FileResponse, StreamingResponse
from plain.http import Request as HttpRequest

from ..accesslog import log_access
from ..util import http_date
from .response import FileWrapper, _decode_path

log = logging.getLogger("plain.server")

# Maximum request body size per H2 stream (10 MiB)
MAX_H2_REQUEST_BODY = 10 * 1024 * 1024

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


def _graceful_close(sock: socket.socket) -> None:
    """Close a socket gracefully to avoid TCP RST.

    Shuts down the write side, drains any remaining data from the peer,
    then closes the socket. This ensures the peer sees a clean FIN
    instead of a RST.
    """
    try:
        sock.shutdown(socket.SHUT_WR)
    except OSError:
        try:
            sock.close()
        except OSError:
            pass
        return

    # Drain remaining data so the kernel doesn't RST (cap at 128 KB)
    try:
        sock.settimeout(1.0)
        remaining = 128 * 1024
        while remaining > 0:
            chunk = sock.recv(min(remaining, 65535))
            if not chunk:
                break
            remaining -= len(chunk)
    except OSError:
        pass

    try:
        sock.close()
    except OSError:
        pass


def _extract_headers_from_stream(
    stream: H2Stream, scheme: str
) -> tuple[str, str, str, str, list[tuple[str, str]]]:
    """Extract method, path, authority, scheme, and regular headers from an H2Stream.

    Returns (method, path, authority, scheme, raw_headers).
    """
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


def _build_http_request(
    method: str,
    path_info: str,
    query: str,
    scheme: str,
    raw_headers: list[tuple[str, str]],
    authority: str,
    client: tuple[str, int] | Any,
    server: tuple[str, int] | Any,
) -> HttpRequest:
    """Build a plain.http.Request from extracted H2 stream data."""
    headers_dict: dict[str, str] = {}
    for name, value in raw_headers:
        if name in headers_dict:
            # Cookie headers must be joined with '; ' per RFC 9113 Section 8.2.3
            sep = "; " if name == "COOKIE" else ","
            headers_dict[name] = f"{headers_dict[name]}{sep}{value}"
        else:
            headers_dict[name] = value

    if isinstance(server, tuple):
        server_name, server_port = str(server[0]), str(server[1])
    elif authority:
        parts = authority.rsplit(":", 1)
        server_name = parts[0]
        server_port = (
            parts[1] if len(parts) > 1 else ("443" if scheme == "https" else "80")
        )
    else:
        server_name, server_port = "localhost", "443"

    if isinstance(client, tuple):
        remote_addr = client[0]
    elif isinstance(client, str):
        remote_addr = client
    else:
        remote_addr = str(client)

    # Apply SCRIPT_NAME prefix handling (same as HTTP/1 path)
    script_name = os.environ.get("SCRIPT_NAME", "")
    path = path_info
    if script_name:
        if path_info.startswith(script_name):
            path_info = path_info[len(script_name) :] or "/"
        path = "{}/{}".format(script_name.rstrip("/"), path_info.replace("/", "", 1))
    else:
        path = path_info

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
    method, path, authority, scheme, raw_headers = _extract_headers_from_stream(
        stream, scheme
    )

    query = ""
    if "?" in path:
        path, query = path.split("?", 1)

    path_bytes = unquote_to_bytes(path)
    path_info = _decode_path(path_bytes) or "/"

    h2_req = H2Request(
        method=method,
        path=path_info,
        query=query,
        headers=raw_headers,
        peer_addr=client,
        scheme=scheme,
    )

    http_request = _build_http_request(
        method, path_info, query, scheme, raw_headers, authority, client, server
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

    for key, value in http_response.header_items():
        lkey = key.lower()
        if lkey not in _H2_SKIP_HEADERS:
            response_headers.append((lkey, value))

    return response_headers


class H2ConnectionState:
    """State for an async HTTP/2 connection.

    Uses asyncio primitives instead of threading ones so the frame read loop
    and per-stream tasks can cooperate on the event loop.  Also holds
    connection-level context (sock, executor, handler, scheme, addresses)
    so per-stream tasks don't need long parameter lists.
    """

    def __init__(
        self,
        conn: h2.connection.H2Connection,
        sock: socket.socket,
        client: tuple[str, int] | Any,
        server: tuple[str, int] | Any,
        handler: Any,
        scheme: str,
        executor: ThreadPoolExecutor,
    ) -> None:
        self.conn = conn
        self.sock = sock
        self.client = client
        self.server = server
        self.handler = handler
        self.scheme = scheme
        self.executor = executor
        self.write_lock = asyncio.Lock()
        self.streams: dict[int, H2Stream] = {}
        self.reset_streams: set[int] = set()
        # Per-stream flow-control events; stream_id 0 = connection-level
        self.window_events: dict[int, asyncio.Event] = {}

    def get_window_event(self, stream_id: int) -> asyncio.Event:
        ev = self.window_events.get(stream_id)
        if ev is None:
            ev = asyncio.Event()
            self.window_events[stream_id] = ev
        return ev

    async def flush(self) -> None:
        """Send any pending h2 data to the socket via the executor."""
        outgoing = self.conn.data_to_send()
        if outgoing:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(self.executor, self.sock.sendall, outgoing)

    def cleanup_stream(self, stream_id: int) -> None:
        """Remove per-stream state after a stream task completes."""
        self.reset_streams.discard(stream_id)
        self.window_events.pop(stream_id, None)


async def async_handle_h2_connection(
    sock: socket.socket,
    client: tuple[str, int] | Any,
    server: tuple[str, int] | Any,
    handler: Any,
    is_ssl: bool,
    executor: ThreadPoolExecutor,
) -> None:
    """Async HTTP/2 connection loop.

    Reads frames from the socket in a dedicated thread (to avoid exhausting
    the shared executor pool), dispatches each completed stream as an
    independent asyncio task.  Flow-control and settings frames are processed
    immediately without blocking on request handling.
    """
    config = h2.config.H2Configuration(client_side=False)
    conn = h2.connection.H2Connection(config=config)
    conn.initiate_connection()

    scheme = "https" if is_ssl else "http"
    state = H2ConnectionState(conn, sock, client, server, handler, scheme, executor)
    loop = asyncio.get_running_loop()

    # Send connection preface
    await loop.run_in_executor(executor, sock.sendall, conn.data_to_send())

    stream_tasks: dict[int, asyncio.Task[None]] = {}

    # Feed incoming data from a dedicated reader thread into an asyncio queue
    # so we never block an executor thread for the connection lifetime.
    recv_queue: asyncio.Queue[bytes | None] = asyncio.Queue()

    # Sentinel used to tell the reader thread to stop.  Set from the
    # finally block before joining; the thread checks it on timeout.
    reader_stop = threading.Event()

    def _reader_thread() -> None:
        try:
            # Use a timeout so the thread doesn't block indefinitely if
            # the socket is never closed (e.g. due to a cleanup bug).
            sock.settimeout(5.0)
            while not reader_stop.is_set():
                try:
                    data = sock.recv(65535)
                except TimeoutError:
                    continue
                loop.call_soon_threadsafe(recv_queue.put_nowait, data)
                if not data:
                    break
        except OSError as e:
            log.debug("H2 reader thread stopped: %s", e)
            loop.call_soon_threadsafe(recv_queue.put_nowait, None)

    reader_thread = threading.Thread(target=_reader_thread, daemon=True)
    reader_thread.start()

    try:
        while True:
            data = await recv_queue.get()
            if not data:
                break

            h2_events = conn.receive_data(data)

            for event in h2_events:
                if isinstance(event, h2.events.RequestReceived):
                    stream = H2Stream(event.stream_id)
                    stream.headers = [
                        (
                            n.decode("utf-8") if isinstance(n, bytes) else n,
                            v.decode("utf-8") if isinstance(v, bytes) else v,
                        )
                        for n, v in event.headers
                    ]
                    state.streams[event.stream_id] = stream

                elif isinstance(event, h2.events.DataReceived):
                    stream = state.streams.get(event.stream_id)
                    if stream is not None:
                        stream.data_size += len(event.data)
                        if stream.data_size > MAX_H2_REQUEST_BODY:
                            conn.reset_stream(event.stream_id)
                            conn.acknowledge_received_data(
                                event.flow_controlled_length, event.stream_id
                            )
                            state.streams.pop(event.stream_id, None)
                            log.warning(
                                "H2 stream %d exceeded max body size (%d bytes)",
                                event.stream_id,
                                MAX_H2_REQUEST_BODY,
                            )
                            continue
                        stream.data.write(event.data)
                        conn.acknowledge_received_data(
                            event.flow_controlled_length, event.stream_id
                        )

                elif isinstance(event, h2.events.StreamEnded):
                    stream = state.streams.pop(event.stream_id, None)
                    if stream is not None:
                        task = loop.create_task(_async_handle_stream(state, stream))
                        stream_tasks[event.stream_id] = task

                        def _on_stream_done(
                            t: asyncio.Task[None], sid: int = event.stream_id
                        ) -> None:
                            stream_tasks.pop(sid, None)
                            state.cleanup_stream(sid)

                        task.add_done_callback(_on_stream_done)

                elif isinstance(event, h2.events.StreamReset):
                    state.streams.pop(event.stream_id, None)
                    state.reset_streams.add(event.stream_id)
                    # Cancel the in-flight task for this stream
                    task = stream_tasks.pop(event.stream_id, None)
                    if task is not None:
                        task.cancel()
                    else:
                        # No task was dispatched; clean up immediately
                        state.cleanup_stream(event.stream_id)

                elif isinstance(event, h2.events.WindowUpdated):
                    # Signal the stream task (or connection-level)
                    ev = state.window_events.get(event.stream_id)
                    if ev is not None:
                        ev.set()
                    # Connection-level window update also wakes all streams
                    if event.stream_id == 0:
                        for ev in state.window_events.values():
                            ev.set()

                elif isinstance(event, h2.events.PriorityUpdated):
                    pass  # advisory only

                elif isinstance(event, h2.events.ConnectionTerminated):
                    # Peer sent GOAWAY
                    break

            # Flush pending data (ACKs, window updates, etc.)
            await state.flush()

    except h2.exceptions.ProtocolError:
        log.debug("HTTP/2 protocol error on async connection from %s", client)
        try:
            await state.flush()
        except OSError:
            pass
    except OSError:
        log.debug("HTTP/2 async connection closed from %s", client)
    except Exception:
        log.exception("Unexpected error in async HTTP/2 connection from %s", client)
    finally:
        # Cancel all in-flight stream tasks
        for task in stream_tasks.values():
            task.cancel()
        if stream_tasks:
            await asyncio.gather(*stream_tasks.values(), return_exceptions=True)

        try:
            conn.close_connection()
            goaway_data = conn.data_to_send()
            if goaway_data:
                await loop.run_in_executor(executor, sock.sendall, goaway_data)
        except Exception:
            pass

        reader_stop.set()
        await loop.run_in_executor(executor, _graceful_close, sock)
        reader_thread.join(timeout=7.0)
        if reader_thread.is_alive():
            log.warning("H2 reader thread did not exit cleanly")


async def _async_handle_stream(
    state: H2ConnectionState,
    stream: H2Stream,
) -> None:
    """Process a single completed HTTP/2 stream as an async task."""
    request_start = datetime.now()

    h2_req, http_request, h2_resp = _prepare_stream_request(
        stream, state.client, state.server, state.scheme
    )

    try:
        signals.request_started.send(sender=None, request=http_request)

        # aget_response runs the full middleware chain in the executor.
        # Async views bridge back to the event loop; sync views run
        # in the executor thread.
        http_response = await state.handler.aget_response(
            http_request, executor=state.executor
        )

        try:
            # Check if stream was reset while we were handling the request
            if stream.stream_id in state.reset_streams:
                return

            await _async_write_h2_response(
                state, stream.stream_id, http_response, h2_resp
            )
        finally:
            request_time = datetime.now() - request_start
            if http_response.log_access:
                log_access(h2_resp, h2_req, request_time)
            if hasattr(http_response, "close"):
                http_response.close()

    except asyncio.CancelledError:
        raise
    except Exception:
        log.exception("Error handling async HTTP/2 request %s", http_request.path_info)
        if stream.stream_id not in state.reset_streams:
            await _async_send_h2_error(state, stream.stream_id, 500)


async def _async_write_h2_response(
    state: H2ConnectionState,
    stream_id: int,
    http_response: Any,
    h2_resp: H2Response,
) -> None:
    """Write a plain.http response as HTTP/2 frames (async)."""
    loop = asyncio.get_running_loop()
    conn = state.conn
    executor = state.executor
    status_code = http_response.status_code
    h2_resp.status = f"{status_code} {http_response.reason_phrase}"

    response_headers = _build_h2_response_headers(http_response)

    is_file = (
        isinstance(http_response, FileResponse)
        and http_response.file_to_stream is not None
    )

    if is_file:
        # Send headers under lock, then stream file chunks outside it
        async with state.write_lock:
            conn.send_headers(stream_id, response_headers)
            await state.flush()

        file_wrapper = FileWrapper(
            http_response.file_to_stream, http_response.block_size
        )
        file_iter = iter(file_wrapper)

        while True:
            chunk = await loop.run_in_executor(executor, next, file_iter, None)
            if chunk is None:
                break
            if chunk:
                h2_resp.sent += len(chunk)
                await _async_send_h2_data(state, stream_id, chunk, end_stream=False)

        async with state.write_lock:
            conn.send_data(stream_id, b"", end_stream=True)
            await state.flush()
    elif isinstance(http_response, AsyncStreamingResponse):
        # Async streaming (SSE, long-lived async generators)
        async with state.write_lock:
            conn.send_headers(stream_id, response_headers)
            await state.flush()

        async for chunk in http_response.streaming_content:
            if chunk:
                if isinstance(chunk, str):
                    chunk = chunk.encode("utf-8")
                h2_resp.sent += len(chunk)
                await _async_send_h2_data(state, stream_id, chunk, end_stream=False)

        async with state.write_lock:
            conn.send_data(stream_id, b"", end_stream=True)
            await state.flush()
    elif isinstance(http_response, StreamingResponse):
        # Stream chunks without buffering the full body in memory
        async with state.write_lock:
            conn.send_headers(stream_id, response_headers)
            await state.flush()

        response_iter = iter(http_response)
        while True:
            chunk = await loop.run_in_executor(executor, next, response_iter, None)
            if chunk is None:
                break
            if chunk:
                h2_resp.sent += len(chunk)
                await _async_send_h2_data(state, stream_id, chunk, end_stream=False)

        async with state.write_lock:
            conn.send_data(stream_id, b"", end_stream=True)
            await state.flush()
    else:
        # Regular response — collect body (usually a single chunk) and send
        def _collect_body() -> bytes:
            parts: list[bytes] = []
            for chunk in http_response:
                if chunk:
                    parts.append(chunk)
            return b"".join(parts)

        body = await loop.run_in_executor(executor, _collect_body)
        h2_resp.sent = len(body)
        h2_resp.response_length = len(body)

        has_cl = any(n == "content-length" for n, _ in response_headers)
        if not has_cl and body:
            response_headers.append(("content-length", str(len(body))))

        if body:
            async with state.write_lock:
                conn.send_headers(stream_id, response_headers)
                await state.flush()
            await _async_send_h2_data(state, stream_id, body, end_stream=True)
        else:
            async with state.write_lock:
                conn.send_headers(stream_id, response_headers, end_stream=True)
                await state.flush()


async def _async_send_h2_data(
    state: H2ConnectionState,
    stream_id: int,
    data: bytes,
    *,
    end_stream: bool = False,
) -> None:
    """Send data respecting HTTP/2 flow control (async, non-blocking)."""
    conn = state.conn
    offset = 0

    # Pre-fetch window events so clears/waits are race-free
    stream_event = state.get_window_event(stream_id)
    conn_event = state.get_window_event(0)

    while offset < len(data):
        # Clear events *before* checking the window so we never lose
        # a WindowUpdated that arrives between the check and the wait.
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

            # Window exhausted — flush pending data before waiting
            await state.flush()

        # Wait for a window update (set by the read loop).
        # We create short-lived tasks to race the two events; the loser
        # is cancelled immediately so nothing leaks.
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
            raise
        for p in pending:
            p.cancel()

        if not done:
            # Timed out waiting for flow-control window update.
            # Reset the stream so the client knows the response is incomplete
            # rather than silently truncating it.
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
    """Send a simple error response on an HTTP/2 stream (async)."""
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
