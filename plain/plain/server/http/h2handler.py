from __future__ import annotations

import asyncio
import io
import logging
import os
import selectors
import socket
import threading
from collections import deque
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


def _invoke_channel_method(
    method: Any,
    async_loop: asyncio.AbstractEventLoop | None,
    *args: Any,
) -> Any:
    """Call a Channel method, supporting both sync and async implementations."""
    if asyncio.iscoroutinefunction(method):
        if async_loop is None:
            raise RuntimeError("Async channel methods require an async event loop")
        future = asyncio.run_coroutine_threadsafe(method(*args), async_loop)
        return future.result(timeout=10)
    return method(*args)


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
    Provides a thread-safe outbound queue (used by H2SSEConnection on the
    async thread) plus a wakeup pipe so the frame loop can react to
    queued data without blocking on sock.recv().
    """

    def __init__(
        self,
        conn: h2.connection.H2Connection,
        sock: socket.socket,
        connection_manager: Any | None = None,
        async_loop: asyncio.AbstractEventLoop | None = None,
    ) -> None:
        self.conn = conn
        self.sock = sock
        self.write_lock = threading.Lock()
        self.streams: dict[int, H2Stream] = {}
        self.connection_manager = connection_manager
        self.async_loop = async_loop

        # Channel streams that are kept open for SSE
        self.channel_streams: dict[int, Any] = {}

        # Wakeup pipe for cross-thread signaling
        self._wakeup_r, self._wakeup_w = os.pipe()
        os.set_blocking(self._wakeup_r, False)
        os.set_blocking(self._wakeup_w, False)

        # Thread-safe outbound queue: (stream_id, data | None)
        # data=None means close the stream
        self._outbound: deque[tuple[int, bytes | None]] = deque()

    @property
    def wakeup_read_fd(self) -> int:
        return self._wakeup_r

    def enqueue_data(self, stream_id: int, data: bytes) -> None:
        """Enqueue SSE data to be sent as HTTP/2 DATA frames.

        Called from the async event loop thread. Thread-safe because
        deque.append is atomic under CPython GIL.
        """
        self._outbound.append((stream_id, data))
        try:
            os.write(self._wakeup_w, b"\x00")
        except OSError:
            pass  # Pipe full — frame loop will still drain

    def enqueue_close(self, stream_id: int) -> None:
        """Enqueue a stream close. Called from the async thread."""
        self._outbound.append((stream_id, None))
        try:
            os.write(self._wakeup_w, b"\x00")
        except OSError:
            pass

    def drain_outbound(self) -> None:
        """Flush queued outbound data as HTTP/2 DATA frames.

        Called ONLY from the frame loop thread — sole owner of h2 state.
        """
        # Drain the wakeup pipe
        try:
            while os.read(self._wakeup_r, 4096):
                pass
        except OSError:
            pass

        while True:
            try:
                stream_id, data = self._outbound.popleft()
            except IndexError:
                break

            if stream_id not in self.channel_streams:
                continue  # Stream already closed/removed

            if data is None:
                # Close the stream
                try:
                    self.conn.send_data(stream_id, b"", end_stream=True)
                    self.sock.sendall(self.conn.data_to_send())
                except Exception:
                    pass
                self.channel_streams.pop(stream_id, None)
            else:
                # Send SSE data as HTTP/2 DATA frames
                try:
                    _send_h2_data(
                        self.conn, self.sock, stream_id, data, end_stream=False
                    )
                except Exception:
                    log.debug("Error sending channel data on stream %d", stream_id)
                    self.channel_streams.pop(stream_id, None)

    def close_pipes(self) -> None:
        """Close the wakeup pipe fds."""
        try:
            os.close(self._wakeup_r)
        except OSError:
            pass
        try:
            os.close(self._wakeup_w)
        except OSError:
            pass


def handle_h2_connection(
    sock: socket.socket,
    client: tuple[str, int] | Any,
    server: tuple[str, int] | Any,
    handler: Any,
    is_ssl: bool,
    connection_manager: Any | None = None,
    async_loop: asyncio.AbstractEventLoop | None = None,
) -> None:
    """Run the HTTP/2 connection loop on a single socket.

    Reads frames from the socket, assembles complete requests per stream,
    and dispatches each to the handler. Responses are serialized back
    through the h2 state machine.

    Uses a selector-based loop that watches both the socket and a wakeup
    pipe, so channel events from the async thread can be flushed without
    blocking on sock.recv().

    This function runs in a worker thread.
    """
    config = h2.config.H2Configuration(client_side=False)
    conn = h2.connection.H2Connection(config=config)
    conn.initiate_connection()
    sock.sendall(conn.data_to_send())

    state = H2ConnectionState(
        conn, sock, connection_manager=connection_manager, async_loop=async_loop
    )
    scheme = "https" if is_ssl else "http"

    sel = selectors.DefaultSelector()
    sel.register(sock, selectors.EVENT_READ)
    sel.register(state.wakeup_read_fd, selectors.EVENT_READ)

    try:
        while True:
            events = sel.select(timeout=30.0)

            for key, _ in events:
                if key.fileobj is sock:
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
                                # Check for channel match before normal dispatch
                                if not _try_channel_stream(
                                    state, stream, client, server, scheme
                                ):
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
                            # Clean up channel stream if it was one
                            h2_sse_conn = state.channel_streams.pop(
                                event.stream_id, None
                            )
                            if h2_sse_conn is not None:
                                h2_sse_conn.close()
                                if (
                                    state.connection_manager is not None
                                    and state.async_loop is not None
                                ):
                                    state.async_loop.call_soon_threadsafe(
                                        state.connection_manager.remove_connection,
                                        h2_sse_conn,
                                    )

                        elif isinstance(event, h2.events.WindowUpdated):
                            pass  # h2 handles flow control internally

                        elif isinstance(event, h2.events.ConnectionTerminated):
                            return

                    # Send any pending data (ACKs, window updates, etc.)
                    outgoing = conn.data_to_send()
                    if outgoing:
                        sock.sendall(outgoing)

                elif key.fd == state.wakeup_read_fd:
                    state.drain_outbound()

            if not events:
                # Timeout — flush any pending outbound data
                state.drain_outbound()

    except h2.exceptions.ProtocolError:
        log.debug("HTTP/2 protocol error on connection from %s", client)
    except OSError:
        log.debug("HTTP/2 connection closed from %s", client)
    except Exception:
        log.exception("Unexpected error in HTTP/2 connection from %s", client)
    finally:
        # Close all channel streams
        for h2_sse_conn in state.channel_streams.values():
            h2_sse_conn.close()
            if state.connection_manager is not None and state.async_loop is not None:
                state.async_loop.call_soon_threadsafe(
                    state.connection_manager.remove_connection,
                    h2_sse_conn,
                )
        state.channel_streams.clear()

        sel.unregister(sock)
        sel.unregister(state.wakeup_read_fd)
        sel.close()
        state.close_pipes()

        try:
            conn.close_connection()
            sock.sendall(conn.data_to_send())
        except Exception:
            pass
        try:
            sock.close()
        except Exception:
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


def _try_channel_stream(
    state: H2ConnectionState,
    stream: H2Stream,
    client: tuple[str, int] | Any,
    server: tuple[str, int] | Any,
    scheme: str,
) -> bool:
    """Check if a completed stream matches a channel and set up SSE over HTTP/2.

    Returns True if the stream was handled as a channel (caller should skip
    normal request dispatch). Returns False for normal requests.
    """
    if state.connection_manager is None or state.async_loop is None:
        return False

    try:
        from plain.realtime.registry import realtime_registry
    except ImportError:
        return False

    method, path, authority, scheme, raw_headers = _extract_headers_from_stream(
        stream, scheme
    )

    # Split path and query
    query = ""
    if "?" in path:
        path, query = path.split("?", 1)

    path_bytes = unquote_to_bytes(path)
    path_info = _decode_path(path_bytes) or "/"

    channel = realtime_registry.match(path_info)
    if channel is None:
        return False

    # Build request for authorization
    http_request = _build_http_request(
        method, path_info, query, scheme, raw_headers, authority, client, server
    )

    # Set the body
    stream.data.seek(0)
    http_request._stream = stream.data
    http_request._read_started = False

    if not _invoke_channel_method(channel.authorize, state.async_loop, http_request):
        _send_h2_error(state.conn, state.sock, state.write_lock, stream.stream_id, 403)
        return True

    subscriptions = _invoke_channel_method(
        channel.subscribe, state.async_loop, http_request
    )
    if not subscriptions:
        _send_h2_error(state.conn, state.sock, state.write_lock, stream.stream_id, 400)
        return True

    # Send SSE response headers (keep stream open — no end_stream)
    response_headers = [
        (":status", "200"),
        ("content-type", "text/event-stream"),
        ("cache-control", "no-cache"),
        ("server", "plain"),
        ("date", http_date()),
    ]

    state.conn.send_headers(stream.stream_id, response_headers)
    state.sock.sendall(state.conn.data_to_send())

    # Create the H2SSEConnection and register it
    from plain.realtime.h2 import H2SSEConnection

    h2_sse_conn = H2SSEConnection(state, stream.stream_id, channel, subscriptions)
    state.channel_streams[stream.stream_id] = h2_sse_conn

    state.async_loop.call_soon_threadsafe(
        state.connection_manager.accept_h2_connection,
        h2_sse_conn,
    )

    return True


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

    method, path, authority, scheme, raw_headers = _extract_headers_from_stream(
        stream, scheme
    )

    # Split path and query
    query = ""
    if "?" in path:
        path, query = path.split("?", 1)

    # Decode path
    path_bytes = unquote_to_bytes(path)
    path_info = _decode_path(path_bytes) or "/"

    # Build the H2Request for access logging
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

    # Set the body
    stream.data.seek(0)
    http_request._stream = stream.data
    http_request._read_started = False

    h2_resp = H2Response()

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
        log.exception("Error handling HTTP/2 request %s", path)
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

    # Build response headers
    response_headers = [
        (":status", str(status_code)),
        ("server", "plain"),
        ("date", http_date()),
    ]

    for key, value in http_response.headers.items():
        if value is not None:
            lkey = key.lower()
            # Skip hop-by-hop headers that don't apply to HTTP/2
            if lkey in ("connection", "transfer-encoding", "keep-alive", "upgrade"):
                continue
            response_headers.append((lkey, value))

    # Add cookies
    for cookie in http_response.cookies.values():
        response_headers.append(("set-cookie", cookie.output(header="")))

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
            # Re-read — the peer may have sent WINDOW_UPDATE
            incoming = sock.recv(65535)
            if incoming:
                conn.receive_data(incoming)
            max_size = conn.local_flow_control_window(stream_id)
            if max_size <= 0:
                # Still no window — send what we can
                max_size = 1

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
