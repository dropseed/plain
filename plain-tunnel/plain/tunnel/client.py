from __future__ import annotations

import asyncio
import json
import logging
import math
from typing import Any
from urllib.parse import urlparse

import click
import httpx
import websockets


class TunnelClient:
    def __init__(
        self, *, destination_url: str, subdomain: str, tunnel_host: str, log_level: str
    ) -> None:
        self.destination_url = destination_url
        self.subdomain = subdomain
        self.tunnel_host = tunnel_host

        self.tunnel_http_url = f"https://{subdomain}.{tunnel_host}"
        self.tunnel_websocket_url = f"wss://{subdomain}.{tunnel_host}"

        self.logger = logging.getLogger(__name__)
        level = getattr(logging, log_level.upper())
        self.logger.setLevel(level)
        self.logger.propagate = False
        handler = logging.StreamHandler()
        handler.setLevel(level)
        handler.setFormatter(logging.Formatter("%(message)s"))
        self.logger.addHandler(handler)

        self.pending_requests: dict[str, dict[str, Any]] = {}
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
                    await self.handle_messages(websocket)
            except asyncio.CancelledError:
                self.logger.debug("Connection cancelled")
                break
            except (websockets.ConnectionClosed, ConnectionError, Exception) as e:
                if self.stop_event.is_set():
                    self.logger.debug("Stopping reconnect attempts due to shutdown")
                    break
                label = (
                    "Connection lost"
                    if isinstance(e, websockets.ConnectionClosed | ConnectionError)
                    else "Unexpected error"
                )
                click.secho(
                    f"{label}: {e}. Retrying in {retry_delay:.0f}s...",
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
        offset = 0

        id_length = int.from_bytes(chunk_data[offset : offset + 4], byteorder="little")
        offset += 4

        request_id = chunk_data[offset : offset + id_length].decode("utf-8")
        offset += id_length

        chunk_index = int.from_bytes(
            chunk_data[offset : offset + 4], byteorder="little"
        )
        offset += 4

        total_chunks = int.from_bytes(
            chunk_data[offset : offset + 4], byteorder="little"
        )
        offset += 4

        body_chunk = chunk_data[offset:]

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
            self.logger.error(f"Error processing request: {task.exception()}")

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

        parsed_url = urlparse(request_metadata["url"])
        path_and_query = parsed_url.path
        if parsed_url.query:
            path_and_query += f"?{parsed_url.query}"
        forward_url = self.destination_url + path_and_query

        self.logger.debug(f"Forwarding request to: {forward_url}")

        async with httpx.AsyncClient(follow_redirects=False, verify=False) as client:
            try:
                response = await client.request(
                    method=request_metadata["method"],
                    url=forward_url,
                    headers=request_metadata["headers"],
                    content=body_data,
                )
                response_body = response.content
                response_headers = dict(response.headers)
                response_status = response.status_code
                self.logger.debug(
                    f"Received response with status code: {response_status}"
                )
            except httpx.ConnectError as e:
                self.logger.error(f"Connection error forwarding request: {e}")
                response_body = b""
                response_headers = {}
                response_status = 502

        self.logger.info(
            f"{click.style(request_metadata['method'], bold=True)} {request_metadata['url']} {response_status}"
        )

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
                body_chunk = response_body[chunk_start:chunk_end]

                chunk_index_bytes = i.to_bytes(4, byteorder="little")
                total_chunks_bytes = total_body_chunks.to_bytes(4, byteorder="little")
                message = id_bytes + chunk_index_bytes + total_chunks_bytes + body_chunk
                await websocket.send(message)
                self.logger.debug(
                    f"Sent body chunk {i + 1}/{total_body_chunks} for ID: {request_id}"
                )

    def run(self) -> None:
        try:
            asyncio.run(self.connect())
        except KeyboardInterrupt:
            self.logger.debug("Received exit signal")
