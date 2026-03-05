from __future__ import annotations

import asyncio
import io
import logging
import socket
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import TYPE_CHECKING, Any
from urllib.parse import unquote_to_bytes

import h2.config
import h2.connection
import h2.events
import h2.exceptions

from plain import signals
from plain.http import FileResponse
from plain.http import Request as HttpRequest

from ..accesslog import log_access
from ..util import http_date
from .response import FileWrapper, _decode_path

if TYPE_CHECKING:
    pass

log = logging.getLogger("plain.server")


class H2Stream:
    """Accumulates headers and data for a single HTTP/2 stream."""

    __slots__ = ("stream_id", "headers", "data", "complete")

    def __init__(self, stream_id: int) -> None:
        self.stream_id = stream_id
        self.headers: list[tuple[str, str]] = []
        self.data = io.BytesIO()
        self.complete = False


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
        self.remote_addr = peer_addr
        self.version = (2, 0)
        self.scheme = scheme

    def should_close(self) -> bool:
        return False


class H2Response:
    """Tracks status/size for access logging of an HTTP/2 response."""

    def __init__(self) -> None:
        self.status: str | None = None
        self.status_code: int | None = None
        self.sent: int = 0
        self.response_length: int | None = None
        self.headers_sent: bool = False


class H2ConnectionState:
    """Consolidated state for an HTTP/2 connection.

    Owns the h2 connection, socket, write lock, and stream tracking.
    """

    def __init__(
        self,
        conn: h2.connection.H2Connection,
        sock: socket.socket,
    ) -> None:
        self.conn = conn
        self.sock = sock
        self.write_lock = threading.Lock()
        self.streams: dict[int, H2Stream] = {}


def handle_h2_connection(
    sock: socket.socket,
    client: tuple[str, int] | Any,
    server: tuple[str, int] | Any,
    handler: Any,
    is_ssl: bool,
) -> None:
    """Run the HTTP/2 connection loop on a single socket.

    Reads frames from the socket, assembles complete requests per stream,
    and dispatches each to the handler. Responses are serialized back
    through the h2 state machine.

    This function runs in a worker thread.
    """
    config = h2.config.H2Configuration(client_side=False)
    conn = h2.connection.H2Connection(config=config)
    conn.initiate_connection()
    sock.sendall(conn.data_to_send())

    state = H2ConnectionState(conn, sock)
    scheme = "https" if is_ssl else "http"

    try:
        while True:
            data = sock.recv(65535)
            if not data:
                return

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
                        stream.data.write(event.data)
                        conn.acknowledge_received_data(
                            event.flow_controlled_length, event.stream_id
                        )

                elif isinstance(event, h2.events.StreamEnded):
                    stream = state.streams.pop(event.stream_id, None)
                    if stream is not None:
                        stream.complete = True
                        _handle_stream(
                            state,
                            stream,
                            client,
                            server,
                            handler,
                            scheme,
                        )

                elif isinstance(event, h2.events.StreamReset):
                    state.streams.pop(event.stream_id, None)

                elif isinstance(event, h2.events.WindowUpdated):
                    pass  # h2 handles flow control internally

                elif isinstance(event, h2.events.PriorityUpdated):
                    pass  # advisory only; no action needed

                elif isinstance(event, h2.events.ConnectionTerminated):
                    return

            # Send any pending data (ACKs, window updates, etc.)
            outgoing = conn.data_to_send()
            if outgoing:
                sock.sendall(outgoing)

    except h2.exceptions.ProtocolError:
        log.debug("HTTP/2 protocol error on connection from %s", client)
        # h2 queues a GOAWAY when it raises ProtocolError — flush it
        try:
            sock.sendall(conn.data_to_send())
        except OSError:
            pass
    except OSError:
        log.debug("HTTP/2 connection closed from %s", client)
    except Exception:
        log.exception("Unexpected error in HTTP/2 connection from %s", client)
    finally:
        try:
            conn.close_connection()
            sock.sendall(conn.data_to_send())
        except Exception:
            pass
        _graceful_close(sock)


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
            headers_dict[name] = f"{headers_dict[name]},{value}"
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

    return HttpRequest(
        method=method,
        path=path_info,
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
    """Build logging and HTTP request objects from a completed H2 stream.

    Shared by both the sync and async stream handlers.
    """
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
    """Build HTTP/2 response headers from an http_response.

    Shared by both the sync and async response writers.
    """
    status_code = http_response.status_code
    response_headers: list[tuple[str, str]] = [
        (":status", str(status_code)),
        ("server", "plain"),
        ("date", http_date()),
    ]

    for key, value in http_response.headers.items():
        if value is not None:
            lkey = key.lower()
            if lkey in ("connection", "transfer-encoding", "keep-alive", "upgrade"):
                continue
            response_headers.append((lkey, value))

    for cookie in http_response.cookies.values():
        response_headers.append(("set-cookie", cookie.output(header="")))

    return response_headers


def _handle_stream(
    state: H2ConnectionState,
    stream: H2Stream,
    client: tuple[str, int] | Any,
    server: tuple[str, int] | Any,
    handler: Any,
    scheme: str,
) -> None:
    """Process a single completed HTTP/2 stream."""
    request_start = datetime.now()

    h2_req, http_request, h2_resp = _prepare_stream_request(
        stream, client, server, scheme
    )

    try:
        signals.request_started.send(sender=None, request=http_request)
        http_response = handler.get_response(http_request)

        try:
            _write_h2_response(
                state.conn,
                state.sock,
                state.write_lock,
                stream.stream_id,
                http_response,
                h2_resp,
            )
        finally:
            request_time = datetime.now() - request_start
            if http_response.log_access:
                log_access(h2_resp, h2_req, request_time)
            if hasattr(http_response, "close"):
                http_response.close()

    except Exception:
        log.exception("Error handling HTTP/2 request %s", http_request.path_info)
        _send_h2_error(state.conn, state.sock, state.write_lock, stream.stream_id, 500)


def _write_h2_response(
    conn: h2.connection.H2Connection,
    sock: socket.socket,
    write_lock: threading.Lock,
    stream_id: int,
    http_response: Any,
    h2_resp: H2Response,
) -> None:
    """Write a plain.http response as HTTP/2 frames."""
    status_code = http_response.status_code
    h2_resp.status = f"{status_code} {http_response.reason_phrase}"
    h2_resp.status_code = status_code

    response_headers = _build_h2_response_headers(http_response)

    # Send headers
    with write_lock:
        if (
            isinstance(http_response, FileResponse)
            and http_response.file_to_stream is not None
        ):
            conn.send_headers(stream_id, response_headers)
            sock.sendall(conn.data_to_send())

            # Stream file data
            file_wrapper = FileWrapper(
                http_response.file_to_stream, http_response.block_size
            )
            _write_h2_file(conn, sock, write_lock, stream_id, file_wrapper, h2_resp)
        else:
            # Collect body chunks
            body_parts: list[bytes] = []
            for chunk in http_response:
                if chunk:
                    body_parts.append(chunk)

            body = b"".join(body_parts)
            h2_resp.sent = len(body)
            h2_resp.response_length = len(body)

            # Add content-length if not already set
            has_cl = any(n == "content-length" for n, _ in response_headers)
            if not has_cl and body:
                response_headers.append(("content-length", str(len(body))))

            if body:
                conn.send_headers(stream_id, response_headers)
                sock.sendall(conn.data_to_send())
                _send_h2_data(conn, sock, stream_id, body, end_stream=True)
            else:
                conn.send_headers(stream_id, response_headers, end_stream=True)
                sock.sendall(conn.data_to_send())


def _write_h2_file(
    conn: h2.connection.H2Connection,
    sock: socket.socket,
    write_lock: threading.Lock,
    stream_id: int,
    file_wrapper: FileWrapper,
    h2_resp: H2Response,
) -> None:
    """Stream a file response over HTTP/2."""
    try:
        for chunk in file_wrapper:
            if chunk:
                h2_resp.sent += len(chunk)
                with write_lock:
                    _send_h2_data(conn, sock, stream_id, chunk, end_stream=False)
    except IndexError:
        pass  # FileWrapper raises IndexError when done

    with write_lock:
        conn.send_data(stream_id, b"", end_stream=True)
        sock.sendall(conn.data_to_send())


def _send_h2_data(
    conn: h2.connection.H2Connection,
    sock: socket.socket,
    stream_id: int,
    data: bytes,
    *,
    end_stream: bool = False,
) -> None:
    """Send data respecting HTTP/2 flow control windows."""
    offset = 0
    while offset < len(data):
        # Check how much we're allowed to send
        max_size = conn.local_flow_control_window(stream_id)
        if max_size <= 0:
            # Need to flush and wait for window update
            sock.sendall(conn.data_to_send())
            sock.settimeout(5.0)
            try:
                incoming = sock.recv(65535)
            except TimeoutError:
                return  # peer never sent WINDOW_UPDATE; give up
            finally:
                sock.settimeout(None)
            if incoming:
                conn.receive_data(incoming)
            max_size = conn.local_flow_control_window(stream_id)
            if max_size <= 0:
                return  # window still exhausted after wait; give up

        # Also respect max frame size
        chunk_size = min(max_size, len(data) - offset, conn.max_outbound_frame_size)
        chunk = data[offset : offset + chunk_size]
        is_last = (offset + chunk_size >= len(data)) and end_stream
        conn.send_data(stream_id, chunk, end_stream=is_last)
        sock.sendall(conn.data_to_send())
        offset += chunk_size

    if end_stream and offset == 0:
        # Empty body with end_stream
        conn.send_data(stream_id, b"", end_stream=True)
        sock.sendall(conn.data_to_send())


def _send_h2_error(
    conn: h2.connection.H2Connection,
    sock: socket.socket,
    write_lock: threading.Lock,
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
        with write_lock:
            conn.send_headers(stream_id, headers)
            sock.sendall(conn.data_to_send())
            conn.send_data(stream_id, body, end_stream=True)
            sock.sendall(conn.data_to_send())
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Async HTTP/2 handler
# ---------------------------------------------------------------------------


class AsyncH2ConnectionState:
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
    state = AsyncH2ConnectionState(
        conn, sock, client, server, handler, scheme, executor
    )
    loop = asyncio.get_running_loop()

    # Send connection preface
    sock.sendall(conn.data_to_send())

    stream_tasks: dict[int, asyncio.Task[None]] = {}

    # Feed incoming data from a dedicated reader thread into an asyncio queue
    # so we never block an executor thread for the connection lifetime.
    recv_queue: asyncio.Queue[bytes | None] = asyncio.Queue()

    def _reader_thread() -> None:
        try:
            while True:
                data = sock.recv(65535)
                loop.call_soon_threadsafe(recv_queue.put_nowait, data)
                if not data:
                    break
        except OSError:
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
                        stream.data.write(event.data)
                        conn.acknowledge_received_data(
                            event.flow_controlled_length, event.stream_id
                        )

                elif isinstance(event, h2.events.StreamEnded):
                    stream = state.streams.pop(event.stream_id, None)
                    if stream is not None:
                        stream.complete = True
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
            outgoing = conn.data_to_send()
            if outgoing:
                sock.sendall(outgoing)

    except h2.exceptions.ProtocolError:
        log.debug("HTTP/2 protocol error on async connection from %s", client)
        try:
            sock.sendall(conn.data_to_send())
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
            sock.sendall(conn.data_to_send())
        except Exception:
            pass

        _graceful_close(sock)
        reader_thread.join(timeout=2.0)


async def _async_handle_stream(
    state: AsyncH2ConnectionState,
    stream: H2Stream,
) -> None:
    """Process a single completed HTTP/2 stream as an async task."""
    loop = asyncio.get_running_loop()
    request_start = datetime.now()

    h2_req, http_request, h2_resp = _prepare_stream_request(
        stream, state.client, state.server, state.scheme
    )

    try:
        signals.request_started.send(sender=None, request=http_request)

        # Resolve URL to check if view is async
        from plain.urls import get_resolver

        view_is_async = False
        try:
            resolver_match = get_resolver().resolve(http_request.path_info)
            http_request.resolver_match = resolver_match
            view_func = resolver_match.view
            view_is_async = getattr(view_func, "view_is_async", False)
        except Exception:
            pass  # middleware will handle 404

        if view_is_async:
            http_response = await state.handler.aget_response(http_request)
        else:
            http_response = await loop.run_in_executor(
                state.executor, state.handler.get_response, http_request
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
        await _async_send_h2_error(state, stream.stream_id, 500)


async def _async_write_h2_response(
    state: AsyncH2ConnectionState,
    stream_id: int,
    http_response: Any,
    h2_resp: H2Response,
) -> None:
    """Write a plain.http response as HTTP/2 frames (async)."""
    loop = asyncio.get_running_loop()
    conn = state.conn
    sock = state.sock
    executor = state.executor
    status_code = http_response.status_code
    h2_resp.status = f"{status_code} {http_response.reason_phrase}"
    h2_resp.status_code = status_code

    response_headers = _build_h2_response_headers(http_response)

    is_file = (
        isinstance(http_response, FileResponse)
        and http_response.file_to_stream is not None
    )

    async with state.write_lock:
        if is_file:
            conn.send_headers(stream_id, response_headers)
            outgoing = conn.data_to_send()
            if outgoing:
                await loop.run_in_executor(executor, sock.sendall, outgoing)

            # Set up file wrapper (chunks read one at a time below)
            file_wrapper = FileWrapper(
                http_response.file_to_stream, http_response.block_size
            )
            file_iter = iter(file_wrapper)

            # Release lock for per-chunk sending (flow control may need to wait)
        else:
            # Collect body in executor for sync responses
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
                conn.send_headers(stream_id, response_headers)
                outgoing = conn.data_to_send()
                if outgoing:
                    await loop.run_in_executor(executor, sock.sendall, outgoing)
            else:
                conn.send_headers(stream_id, response_headers, end_stream=True)
                outgoing = conn.data_to_send()
                if outgoing:
                    await loop.run_in_executor(executor, sock.sendall, outgoing)
                return

    # Send body data with flow control (outside initial lock scope)
    if is_file:
        while True:
            chunk = await loop.run_in_executor(executor, next, file_iter, None)
            if chunk is None:
                break
            if chunk:
                h2_resp.sent += len(chunk)
                await _async_send_h2_data(state, stream_id, chunk, end_stream=False)

        async with state.write_lock:
            conn.send_data(stream_id, b"", end_stream=True)
            outgoing = conn.data_to_send()
            if outgoing:
                await loop.run_in_executor(executor, sock.sendall, outgoing)
    else:
        await _async_send_h2_data(state, stream_id, body, end_stream=True)


async def _async_send_h2_data(
    state: AsyncH2ConnectionState,
    stream_id: int,
    data: bytes,
    *,
    end_stream: bool = False,
) -> None:
    """Send data respecting HTTP/2 flow control (async, non-blocking)."""
    loop = asyncio.get_running_loop()
    conn = state.conn
    sock = state.sock
    executor = state.executor
    offset = 0

    while offset < len(data):
        async with state.write_lock:
            max_size = conn.local_flow_control_window(stream_id)
            if max_size > 0:
                # Window available — send in this lock acquisition
                chunk_size = min(
                    max_size, len(data) - offset, conn.max_outbound_frame_size
                )
                chunk = data[offset : offset + chunk_size]
                is_last = (offset + chunk_size >= len(data)) and end_stream
                conn.send_data(stream_id, chunk, end_stream=is_last)
                outgoing = conn.data_to_send()
                if outgoing:
                    await loop.run_in_executor(executor, sock.sendall, outgoing)
                offset += chunk_size
                continue

            # Window exhausted — flush pending data before waiting
            outgoing = conn.data_to_send()
            if outgoing:
                await loop.run_in_executor(executor, sock.sendall, outgoing)

        # Wait for a window update (set by the read loop)
        stream_event = state.get_window_event(stream_id)
        conn_event = state.get_window_event(0)
        stream_event.clear()
        conn_event.clear()

        done, pending = await asyncio.wait(
            [
                asyncio.ensure_future(stream_event.wait()),
                asyncio.ensure_future(conn_event.wait()),
            ],
            timeout=5.0,
            return_when=asyncio.FIRST_COMPLETED,
        )
        for p in pending:
            p.cancel()

        if not done:
            return  # Timed out waiting for window update; give up

    if end_stream and offset == 0:
        async with state.write_lock:
            conn.send_data(stream_id, b"", end_stream=True)
            outgoing = conn.data_to_send()
            if outgoing:
                await loop.run_in_executor(executor, sock.sendall, outgoing)


async def _async_send_h2_error(
    state: AsyncH2ConnectionState,
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
            state.sock.sendall(state.conn.data_to_send())
    except Exception:
        pass
