from __future__ import annotations

import asyncio
import base64
import json
import logging
import math
import struct
from typing import Any
from urllib.parse import urlparse

import click
import httpx
import websockets

# Bump this when making breaking changes to the WebSocket protocol.
# The server will reject clients with a version lower than its minimum.
PROTOCOL_VERSION = 3


class TunnelClient:
    def __init__(
        self, *, destination_url: str, subdomain: str, tunnel_host: str, log_level: str
    ) -> None:
        self.destination_url = destination_url
        self.subdomain = subdomain
        self.tunnel_host = tunnel_host

        if "localhost" in tunnel_host or "127.0.0.1" in tunnel_host:
            self.tunnel_http_url = f"http://{subdomain}.{tunnel_host}"
            self.tunnel_websocket_url = (
                f"ws://{subdomain}.{tunnel_host}/__tunnel__?v={PROTOCOL_VERSION}"
            )
        else:
            self.tunnel_http_url = f"https://{subdomain}.{tunnel_host}"
            self.tunnel_websocket_url = (
                f"wss://{subdomain}.{tunnel_host}/__tunnel__?v={PROTOCOL_VERSION}"
            )

        self.logger = logging.getLogger(__name__)
        level = getattr(logging, log_level.upper())
        self.logger.setLevel(level)
        self.logger.propagate = False
        handler = logging.StreamHandler()
        handler.setLevel(level)
        handler.setFormatter(logging.Formatter("%(message)s"))
        self.logger.addHandler(handler)

        self.pending_requests: dict[str, dict[str, Any]] = {}
        self.active_streams: dict[str, asyncio.Event] = {}
        self.proxied_websockets: dict[str, Any] = {}
        self.ws_pending_queues: dict[str, asyncio.Queue[dict[str, Any]]] = {}
        self.stop_event = asyncio.Event()

    async def connect(self) -> None:
        retry_delay = 1.0
        max_retry_delay = 30.0
        while not self.stop_event.is_set():
            try:
                self.logger.debug(
                    f"Connecting to WebSocket URL: {self.tunnel_websocket_url}"
                )
                async with websockets.connect(
                    self.tunnel_websocket_url, max_size=None
                ) as websocket:
                    self.logger.debug("WebSocket connection established")
                    click.secho(
                        f"Connected to tunnel {self.tunnel_http_url}", fg="green"
                    )
                    retry_delay = 1.0
                    try:
                        await self.handle_messages(websocket)
                    finally:
                        await self._cleanup_proxied_websockets()
            except asyncio.CancelledError:
                self.logger.debug("Connection cancelled")
                break
            except websockets.InvalidStatus as e:
                if e.response.status_code == 426:
                    body = e.response.body.decode() if e.response.body else ""
                    click.secho(
                        body or "Client version too old. Please upgrade plain.tunnel.",
                        fg="red",
                    )
                    break
                raise
            except (websockets.ConnectionClosed, ConnectionError) as e:
                if self.stop_event.is_set():
                    self.logger.debug("Stopping reconnect attempts due to shutdown")
                    break
                click.secho(
                    f"Connection lost: {e}. Retrying in {retry_delay:.0f}s...",
                    fg="yellow",
                )
                await asyncio.sleep(retry_delay)
                retry_delay = min(retry_delay * 2, max_retry_delay)
            except Exception as e:
                if self.stop_event.is_set():
                    self.logger.debug("Stopping reconnect attempts due to shutdown")
                    break
                click.secho(
                    f"Unexpected error: {e}. Retrying in {retry_delay:.0f}s...",
                    fg="yellow",
                )
                await asyncio.sleep(retry_delay)
                retry_delay = min(retry_delay * 2, max_retry_delay)

    async def handle_messages(self, websocket: Any) -> None:
        try:
            async for message in websocket:
                if isinstance(message, str):
                    data = json.loads(message)
                    msg_type = data.get("type")
                    if msg_type == "ping":
                        self.logger.debug("Received heartbeat ping, sending pong")
                        await websocket.send(json.dumps({"type": "pong"}))
                    elif msg_type == "request":
                        self.logger.debug("Received request metadata from worker")
                        await self.handle_request_metadata(websocket, data)
                    elif msg_type == "stream-cancel":
                        request_id = data.get("id")
                        self.logger.debug(
                            f"Received stream-cancel for request ID: {request_id}"
                        )
                        cancel_event = self.active_streams.get(request_id)
                        if cancel_event:
                            cancel_event.set()
                    elif msg_type == "ws-open":
                        self.logger.debug(f"Received ws-open for ID: {data['id']}")
                        self.ws_pending_queues[data["id"]] = asyncio.Queue()
                        task = asyncio.create_task(
                            self._handle_ws_open(websocket, data)
                        )
                        task.add_done_callback(self._handle_task_exception)
                    elif msg_type == "ws-message":
                        await self._handle_ws_message(data)
                    elif msg_type == "ws-close":
                        await self._handle_ws_close(data)
                    else:
                        self.logger.warning(
                            f"Received unknown message type: {msg_type}"
                        )
                elif isinstance(message, bytes):
                    self.logger.debug("Received binary data from worker")
                    await self.handle_request_body_chunk(websocket, message)
                else:
                    self.logger.warning("Received unknown message format")
        except asyncio.CancelledError:
            self.logger.debug("Message handling cancelled")
        except Exception as e:
            self.logger.error(f"Error in handle_messages: {e}")
            raise

    async def handle_request_metadata(
        self, websocket: Any, data: dict[str, Any]
    ) -> None:
        request_id = data["id"]
        has_body = data.get("has_body", False)
        total_body_chunks = data.get("totalBodyChunks", 0)
        self.pending_requests[request_id] = {
            "metadata": data,
            "body_chunks": {},
            "has_body": has_body,
            "total_body_chunks": total_body_chunks,
        }
        self.logger.debug(
            f"Stored metadata for request ID: {request_id}, has_body: {has_body}"
        )
        await self.check_and_process_request(websocket, request_id)

    async def handle_request_body_chunk(
        self, websocket: Any, chunk_data: bytes
    ) -> None:
        (id_length,) = struct.unpack_from("<I", chunk_data, 0)
        request_id = chunk_data[4 : 4 + id_length].decode("utf-8")
        header_end = 4 + id_length + 8
        chunk_index, total_chunks = struct.unpack_from("<II", chunk_data, 4 + id_length)
        body_chunk = chunk_data[header_end:]

        if request_id in self.pending_requests:
            request = self.pending_requests[request_id]
            request["body_chunks"][chunk_index] = body_chunk
            self.logger.debug(
                f"Stored body chunk {chunk_index + 1}/{total_chunks} for request ID: {request_id}"
            )
            await self.check_and_process_request(websocket, request_id)
        else:
            self.logger.warning(
                f"Received body chunk for unknown or completed request ID: {request_id}"
            )

    async def check_and_process_request(self, websocket: Any, request_id: str) -> None:
        request_data = self.pending_requests.get(request_id)
        if not request_data:
            return

        has_body = request_data["has_body"]
        total_body_chunks = request_data["total_body_chunks"]
        body_chunks = request_data["body_chunks"]

        all_chunks_received = not has_body or len(body_chunks) == total_body_chunks
        if not all_chunks_received:
            return

        for i in range(total_body_chunks):
            if i not in body_chunks:
                self.logger.error(
                    f"Missing chunk {i + 1}/{total_body_chunks} for request ID: {request_id}"
                )
                return

        self.logger.debug(f"Processing request ID: {request_id}")
        del self.pending_requests[request_id]
        task = asyncio.create_task(
            self.process_request(
                websocket,
                request_data["metadata"],
                body_chunks,
                request_id,
            )
        )
        task.add_done_callback(self._handle_task_exception)

    def _handle_task_exception(self, task: asyncio.Task[None]) -> None:
        if not task.cancelled() and task.exception():
            self.logger.error("Error processing request", exc_info=task.exception())

    async def _cleanup_proxied_websockets(self) -> None:
        """Close all proxied WebSocket connections on tunnel disconnect."""
        for ws_id, ws in list(self.proxied_websockets.items()):
            try:
                await ws.close()
            except Exception:
                pass
        self.proxied_websockets.clear()
        self.ws_pending_queues.clear()

    async def process_request(
        self,
        websocket: Any,
        request_metadata: dict[str, Any],
        body_chunks: dict[int, bytes],
        request_id: str,
    ) -> None:
        self.logger.debug(
            f"Processing request: {request_id} {request_metadata['method']} {request_metadata['url']}"
        )

        if request_metadata["has_body"]:
            total_chunks = request_metadata["totalBodyChunks"]
            body_data = b"".join(body_chunks[i] for i in range(total_chunks))
        else:
            body_data = None

        parsed = urlparse(request_metadata["url"])
        path = parsed.path
        if parsed.query:
            path = f"{path}?{parsed.query}"
        forward_url = f"{self.destination_url}{path}"

        self.logger.debug(f"Forwarding request to: {forward_url}")

        async with httpx.AsyncClient(follow_redirects=False, verify=False) as client:
            try:
                async with client.stream(
                    method=request_metadata["method"],
                    url=forward_url,
                    headers=request_metadata["headers"],
                    content=body_data,
                ) as response:
                    response_status = response.status_code
                    response_headers = dict(response.headers)

                    self.logger.info(
                        f"{click.style(request_metadata['method'], bold=True)} {request_metadata['url']} {response_status}"
                    )

                    if self._is_streaming_response(response):
                        await self._handle_streaming_response(
                            websocket,
                            response,
                            request_id,
                            response_status,
                            response_headers,
                        )
                    else:
                        await response.aread()
                        await self._handle_buffered_response(
                            websocket,
                            response.content,
                            request_id,
                            response_status,
                            response_headers,
                        )
            except httpx.ConnectError as e:
                self.logger.error(f"Connection error forwarding request: {e}")
                self.logger.info(
                    f"{click.style(request_metadata['method'], bold=True)} {request_metadata['url']} 502"
                )
                await self._handle_buffered_response(
                    websocket, b"", request_id, 502, {}
                )

    def _is_streaming_response(self, response: httpx.Response) -> bool:
        content_type = response.headers.get("content-type", "")
        return "text/event-stream" in content_type

    async def _handle_buffered_response(
        self,
        websocket: Any,
        response_body: bytes,
        request_id: str,
        response_status: int,
        response_headers: dict[str, str],
    ) -> None:
        has_body = len(response_body) > 0
        max_chunk_size = 1_000_000
        total_body_chunks = (
            math.ceil(len(response_body) / max_chunk_size) if has_body else 0
        )

        response_metadata = {
            "type": "response",
            "id": request_id,
            "status": response_status,
            "headers": list(response_headers.items()),
            "has_body": has_body,
            "totalBodyChunks": total_body_chunks,
        }

        self.logger.debug(
            f"Sending response metadata for ID: {request_id}, has_body: {has_body}"
        )
        await websocket.send(json.dumps(response_metadata))

        if has_body:
            self.logger.debug(
                f"Sending {total_body_chunks} body chunks for ID: {request_id}"
            )
            id_bytes = request_id.encode("utf-8")
            for i in range(total_body_chunks):
                chunk_start = i * max_chunk_size
                chunk_end = min(chunk_start + max_chunk_size, len(response_body))
                header = id_bytes + struct.pack("<II", i, total_body_chunks)
                await websocket.send(header + response_body[chunk_start:chunk_end])
                self.logger.debug(
                    f"Sent body chunk {i + 1}/{total_body_chunks} for ID: {request_id}"
                )

    async def _handle_streaming_response(
        self,
        websocket: Any,
        response: httpx.Response,
        request_id: str,
        response_status: int,
        response_headers: dict[str, str],
    ) -> None:
        cancel_event = asyncio.Event()
        self.active_streams[request_id] = cancel_event

        stream_start = {
            "type": "stream-start",
            "id": request_id,
            "status": response_status,
            "headers": list(response_headers.items()),
        }

        self.logger.debug(f"Sending stream-start for ID: {request_id}")
        await websocket.send(json.dumps(stream_start))

        id_bytes = request_id.encode("utf-8")

        try:
            async for chunk in response.aiter_bytes():
                if cancel_event.is_set():
                    self.logger.debug(
                        f"Stream cancelled by browser for request ID: {request_id}"
                    )
                    break

                await websocket.send(id_bytes + chunk)
            else:
                # Only send stream-end if the loop completed naturally
                # (not cancelled by the server via stream-cancel)
                stream_end = {
                    "type": "stream-end",
                    "id": request_id,
                }
                self.logger.debug(f"Sending stream-end for ID: {request_id}")
                await websocket.send(json.dumps(stream_end))
        except Exception as e:
            self.logger.error(f"Error streaming response for ID {request_id}: {e}")
            stream_error = {
                "type": "stream-error",
                "id": request_id,
                "error": str(e),
            }
            try:
                await websocket.send(json.dumps(stream_error))
            except Exception:
                pass
        finally:
            self.active_streams.pop(request_id, None)

    async def _handle_ws_open(self, tunnel_ws: Any, data: dict[str, Any]) -> None:
        ws_id = data["id"]
        url = data["url"]
        parsed = urlparse(url)
        path = parsed.path
        if parsed.query:
            path = f"{path}?{parsed.query}"

        # Build local WebSocket URL
        dest_parsed = urlparse(self.destination_url)
        if dest_parsed.scheme == "https":
            ws_scheme = "wss"
        else:
            ws_scheme = "ws"
        local_ws_url = f"{ws_scheme}://{dest_parsed.netloc}{path}"

        self.logger.debug(f"Opening local WebSocket for {ws_id}: {local_ws_url}")

        # Forward safe browser headers (cookies, auth, origin) to the local
        # server. Skip hop-by-hop and WebSocket handshake headers since
        # websockets.connect generates its own (including Host from the URL).
        skip_headers = frozenset(
            {
                "host",
                "connection",
                "upgrade",
                "sec-websocket-key",
                "sec-websocket-version",
                "sec-websocket-extensions",
                "sec-websocket-protocol",
                "host",
            }
        )
        forward_headers = {}
        for name, value in data.get("headers", {}).items():
            if name.lower() not in skip_headers:
                forward_headers[name] = value

        try:
            import ssl

            ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE
            local_ws = await websockets.connect(
                local_ws_url,
                ssl=ssl_context if ws_scheme == "wss" else None,
                max_size=None,
                additional_headers=forward_headers,
            )
        except Exception as e:
            self.logger.error(f"Failed to connect local WebSocket for {ws_id}: {e}")
            self.ws_pending_queues.pop(ws_id, None)
            try:
                await tunnel_ws.send(
                    json.dumps(
                        {
                            "type": "ws-close",
                            "id": ws_id,
                            "code": 1011,
                            "reason": str(e),
                        }
                    )
                )
            except Exception:
                pass
            return

        self.proxied_websockets[ws_id] = local_ws

        # Drain any messages that arrived while connecting
        queue = self.ws_pending_queues.pop(ws_id, None)
        if queue is not None:
            while not queue.empty():
                queued = queue.get_nowait()
                try:
                    if queued.get("binary"):
                        await local_ws.send(base64.b64decode(queued["data"]))
                    else:
                        await local_ws.send(queued["data"])
                except Exception as e:
                    self.logger.error(
                        f"Failed to forward queued message to local WebSocket {ws_id}: {e}"
                    )

        self.logger.info(f"WebSocket proxy opened: {ws_id} -> {local_ws_url}")

        # Relay messages from local server back to the tunnel
        try:
            async for message in local_ws:
                if isinstance(message, str):
                    await tunnel_ws.send(
                        json.dumps({"type": "ws-message", "id": ws_id, "data": message})
                    )
                elif isinstance(message, bytes):
                    await tunnel_ws.send(
                        json.dumps(
                            {
                                "type": "ws-message",
                                "id": ws_id,
                                "data": base64.b64encode(message).decode("ascii"),
                                "binary": True,
                            }
                        )
                    )
        except websockets.ConnectionClosed:
            pass
        except Exception as e:
            self.logger.error(f"Error relaying WebSocket {ws_id}: {e}")
        finally:
            self.proxied_websockets.pop(ws_id, None)
            close_code = local_ws.close_code or 1000
            close_reason = local_ws.close_reason or ""
            try:
                await tunnel_ws.send(
                    json.dumps(
                        {
                            "type": "ws-close",
                            "id": ws_id,
                            "code": close_code,
                            "reason": close_reason,
                        }
                    )
                )
            except Exception:
                pass

    async def _handle_ws_message(self, data: dict[str, Any]) -> None:
        ws_id = data["id"]
        local_ws = self.proxied_websockets.get(ws_id)
        if not local_ws:
            # Connection still being established — buffer for later
            queue = self.ws_pending_queues.get(ws_id)
            if queue is not None:
                await queue.put(data)
                return
            self.logger.warning(f"Received ws-message for unknown WebSocket: {ws_id}")
            return
        try:
            if data.get("binary"):
                await local_ws.send(base64.b64decode(data["data"]))
            else:
                await local_ws.send(data["data"])
        except Exception as e:
            self.logger.error(
                f"Failed to forward message to local WebSocket {ws_id}: {e}"
            )

    async def _handle_ws_close(self, data: dict[str, Any]) -> None:
        ws_id = data["id"]
        local_ws = self.proxied_websockets.pop(ws_id, None)
        if not local_ws:
            return
        try:
            await local_ws.close()
        except Exception:
            pass

    def run(self) -> None:
        try:
            asyncio.run(self.connect())
        except KeyboardInterrupt:
            self.logger.debug("Received exit signal")
