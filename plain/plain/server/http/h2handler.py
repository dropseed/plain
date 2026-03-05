from __future__ import annotations

import io
import logging
import socket
import threading
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

    This function runs in a worker thread. For simplicity, streams on a
    single connection are processed sequentially — the multiplexing benefit
    comes from the client being able to pipeline requests without
    head-of-line blocking at the TCP level.
    """
    config = h2.config.H2Configuration(client_side=False)
    conn = h2.connection.H2Connection(config=config)
    conn.initiate_connection()
    sock.sendall(conn.data_to_send())

    # Lock for writing to the h2 connection (needed if we add concurrent
    # stream handling in the future)
    write_lock = threading.Lock()

    streams: dict[int, H2Stream] = {}
    scheme = "https" if is_ssl else "http"

    try:
        while True:
            data = sock.recv(65535)
            if not data:
                break

            events = conn.receive_data(data)

            for event in events:
                if isinstance(event, h2.events.RequestReceived):
                    stream = H2Stream(event.stream_id)
                    stream.headers = [
                        (
                            n.decode("utf-8") if isinstance(n, bytes) else n,
                            v.decode("utf-8") if isinstance(v, bytes) else v,
                        )
                        for n, v in event.headers
                    ]
                    streams[event.stream_id] = stream

                elif isinstance(event, h2.events.DataReceived):
                    stream = streams.get(event.stream_id)
                    if stream is not None:
                        stream.data.write(event.data)
                        conn.acknowledge_received_data(
                            event.flow_controlled_length, event.stream_id
                        )

                elif isinstance(event, h2.events.StreamEnded):
                    stream = streams.pop(event.stream_id, None)
                    if stream is not None:
                        stream.complete = True
                        _handle_stream(
                            conn,
                            sock,
                            write_lock,
                            stream,
                            client,
                            server,
                            handler,
                            scheme,
                        )

                elif isinstance(event, h2.events.StreamReset):
                    streams.pop(event.stream_id, None)

                elif isinstance(event, h2.events.WindowUpdated):
                    pass  # h2 handles flow control internally

                elif isinstance(event, h2.events.ConnectionTerminated):
                    # Client sent GOAWAY
                    return

            # Send any pending data (ACKs, window updates, etc.)
            outgoing = conn.data_to_send()
            if outgoing:
                with write_lock:
                    sock.sendall(outgoing)

    except h2.exceptions.ProtocolError:
        log.debug("HTTP/2 protocol error on connection from %s", client)
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
        try:
            sock.close()
        except Exception:
            pass


def _handle_stream(
    conn: h2.connection.H2Connection,
    sock: socket.socket,
    write_lock: threading.Lock,
    stream: H2Stream,
    client: tuple[str, int] | Any,
    server: tuple[str, int] | Any,
    handler: Any,
    scheme: str,
) -> None:
    """Process a single completed HTTP/2 stream."""
    request_start = datetime.now()

    # Extract pseudo-headers and regular headers
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

    # Add Host header from :authority if not present
    if authority and not any(n == "HOST" for n, _ in raw_headers):
        raw_headers.append(("HOST", authority))

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

    # Build headers dict for plain.http.Request
    headers_dict: dict[str, str] = {}
    for name, value in raw_headers:
        if name in headers_dict:
            headers_dict[name] = f"{headers_dict[name]},{value}"
        else:
            headers_dict[name] = value

    # Resolve server name/port
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

    # Remote address
    if isinstance(client, tuple):
        remote_addr = client[0]
    elif isinstance(client, str):
        remote_addr = client
    else:
        remote_addr = str(client)

    http_request = HttpRequest(
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
                conn, sock, write_lock, stream.stream_id, http_response, h2_resp
            )
        finally:
            request_time = datetime.now() - request_start
            if http_response.log_access:
                log_access(h2_resp, h2_req, request_time)
            if hasattr(http_response, "close"):
                http_response.close()

    except Exception:
        log.exception("Error handling HTTP/2 request %s", path)
        _send_h2_error(conn, sock, write_lock, stream.stream_id, 500)


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
