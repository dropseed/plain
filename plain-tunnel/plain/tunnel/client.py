import asyncio
import json
import logging
import ssl
import urllib.error
import urllib.request
from urllib.parse import urlparse

import click
import websockets


class TunnelClient:
    def __init__(self, *, destination_url, subdomain, tunnel_host, log_level):
        self.destination_url = destination_url
        self.subdomain = subdomain
        self.tunnel_host = tunnel_host

        self.tunnel_http_url = f"https://{subdomain}.{tunnel_host}"
        self.tunnel_websocket_url = f"wss://{subdomain}.{tunnel_host}"

        # Set up logging
        self.logger = logging.getLogger(__name__)
        self.logger.setLevel(getattr(logging, log_level.upper()))
        ch = logging.StreamHandler()
        ch.setLevel(getattr(logging, log_level.upper()))
        formatter = logging.Formatter("%(message)s")
        ch.setFormatter(formatter)
        self.logger.addHandler(ch)

        # Store incoming requests
        self.pending_requests = {}

        # Create the event loop
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.stop_event = asyncio.Event()

    async def connect(self):
        retry_count = 0
        max_retries = 5
        while not self.stop_event.is_set():
            if retry_count >= max_retries:
                self.logger.error(
                    f"Failed to connect after {max_retries} retries. Exiting."
                )
                break
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
                    retry_count = 0  # Reset retry count on successful connection
                    await self.forward_request(websocket)
            except (websockets.ConnectionClosed, ConnectionError) as e:
                if self.stop_event.is_set():
                    self.logger.debug("Stopping reconnect attempts due to shutdown")
                    break
                retry_count += 1
                self.logger.warning(
                    f"Connection lost: {e}. Retrying in 2 seconds... ({retry_count}/{max_retries})"
                )
                await asyncio.sleep(2)
            except asyncio.CancelledError:
                self.logger.debug("Connection cancelled")
                break
            except Exception as e:
                if self.stop_event.is_set():
                    self.logger.debug("Stopping reconnect attempts due to shutdown")
                    break
                retry_count += 1
                self.logger.error(
                    f"Unexpected error: {e}. Retrying in 2 seconds... ({retry_count}/{max_retries})"
                )
                await asyncio.sleep(2)

    async def forward_request(self, websocket):
        try:
            async for message in websocket:
                if isinstance(message, str):
                    # Received text message (metadata)
                    self.logger.debug("Received metadata from worker")
                    data = json.loads(message)
                    await self.handle_request_metadata(websocket, data)
                elif isinstance(message, bytes):
                    # Received binary message (body chunk)
                    self.logger.debug("Received binary data from worker")
                    await self.handle_request_body_chunk(websocket, message)
                else:
                    self.logger.warning("Received unknown message type")
        except asyncio.CancelledError:
            self.logger.debug("Forward request cancelled")
        except Exception as e:
            self.logger.error(f"Error in forward_request: {e}")
            raise

    async def handle_request_metadata(self, websocket, data):
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

    async def handle_request_body_chunk(self, websocket, chunk_data):
        offset = 0

        # Extract id_length
        id_length = int.from_bytes(chunk_data[offset : offset + 4], byteorder="little")
        offset += 4

        # Extract request_id
        request_id = chunk_data[offset : offset + id_length].decode("utf-8")
        offset += id_length

        # Extract chunk_index
        chunk_index = int.from_bytes(
            chunk_data[offset : offset + 4], byteorder="little"
        )
        offset += 4

        # Extract total_chunks
        total_chunks = int.from_bytes(
            chunk_data[offset : offset + 4], byteorder="little"
        )
        offset += 4

        # Extract body_chunk
        body_chunk = chunk_data[offset:]

        # Continue processing as before

        if request_id in self.pending_requests:
            request = self.pending_requests[request_id]
            if "body_chunks" not in request:
                request["body_chunks"] = {}
                request["total_body_chunks"] = total_chunks
            request["body_chunks"][chunk_index] = body_chunk
            self.logger.debug(
                f"Stored body chunk {chunk_index + 1}/{total_chunks} for request ID: {request_id}"
            )
            await self.check_and_process_request(websocket, request_id)
        else:
            self.logger.warning(
                f"Received body chunk for unknown or completed request ID: {request_id}"
            )

    async def check_and_process_request(self, websocket, request_id):
        request_data = self.pending_requests.get(request_id)
        if request_data and request_data["metadata"]:
            has_body = request_data["has_body"]
            total_body_chunks = request_data.get("total_body_chunks", 0)
            body_chunks = request_data.get("body_chunks", {})

            all_chunks_received = not has_body or (
                len(body_chunks) == total_body_chunks
            )

            if all_chunks_received:
                # Ensure all chunks are present
                for i in range(total_body_chunks):
                    if i not in body_chunks:
                        self.logger.error(
                            f"Missing chunk {i + 1}/{total_body_chunks} for request ID: {request_id}"
                        )
                        return

                self.logger.debug(f"Processing request ID: {request_id}")
                await self.process_request(
                    websocket, request_data["metadata"], body_chunks, request_id
                )
                del self.pending_requests[request_id]

    async def process_request(
        self, websocket, request_metadata, body_chunks, request_id
    ):
        self.logger.debug(
            f"Processing request: {request_id} {request_metadata['method']} {request_metadata['url']}"
        )

        # Reassemble body if present
        if request_metadata["has_body"]:
            total_chunks = request_metadata["totalBodyChunks"]
            body_data = b"".join(body_chunks[i] for i in range(total_chunks))
        else:
            body_data = None

        # Parse the original URL to extract the path and query
        parsed_url = urlparse(request_metadata["url"])
        path_and_query = parsed_url.path
        if parsed_url.query:
            path_and_query += f"?{parsed_url.query}"

        # Construct the new URL by appending path and query to destination_url
        forward_url = self.destination_url + path_and_query

        self.logger.debug(f"Forwarding request to: {forward_url}")

        # Create a custom SSL context to ignore SSL verification (if needed)
        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE

        # Prepare the request
        req = urllib.request.Request(
            url=forward_url,
            method=request_metadata["method"],
            data=body_data if body_data else None,
            headers=request_metadata["headers"],  # Headers set directly on the request
        )

        # Override the HTTPErrorProcessor to stop processing redirects
        class NoRedirectProcessor(urllib.request.HTTPErrorProcessor):
            def http_response(self, request, response):
                return response

            https_response = http_response

        # Create a custom opener that uses the NoRedirectProcessor
        opener = urllib.request.build_opener(
            urllib.request.HTTPHandler(),
            urllib.request.HTTPSHandler(
                context=ssl_context
            ),  # Pass the SSL context here
            NoRedirectProcessor(),
        )

        try:
            # Make the request using our custom opener
            with opener.open(req) as response:
                response_body = response.read()
                response_headers = dict(response.getheaders())
                response_status = response.getcode()
                self.logger.debug(
                    f"Received response with status code: {response_status}"
                )

        except urllib.error.HTTPError as e:
            # Non-200 status codes are here (even ones we want)
            self.logger.debug(f"HTTPError forwarding request: {e}")
            response_body = e.read()
            response_headers = dict(e.headers)
            response_status = e.code

        except urllib.error.URLError as e:
            self.logger.error(f"URLError forwarding request: {e}")
            response_body = b""
            response_headers = {}
            response_status = 500

        self.logger.info(
            f"{click.style(request_metadata['method'], bold=True)} {request_metadata['url']} {response_status}"
        )

        has_body = len(response_body) > 0
        max_chunk_size = 1000000  # 1,000,000 bytes
        total_body_chunks = (
            (len(response_body) + max_chunk_size - 1) // max_chunk_size
            if has_body
            else 0
        )

        response_metadata = {
            "id": request_id,
            "status": response_status,
            "headers": list(response_headers.items()),
            "has_body": has_body,
            "totalBodyChunks": total_body_chunks,
        }

        # Send response metadata
        response_metadata_json = json.dumps(response_metadata)
        self.logger.debug(
            f"Sending response metadata for ID: {request_id}, has_body: {has_body}"
        )
        await websocket.send(response_metadata_json)

        # Send response body chunks if present
        if has_body:
            self.logger.debug(
                f"Sending {total_body_chunks} body chunks for ID: {request_id}"
            )
            id_bytes = request_id.encode("utf-8")
            for i in range(total_body_chunks):
                chunk_start = i * max_chunk_size
                chunk_end = min(chunk_start + max_chunk_size, len(response_body))
                body_chunk = response_body[chunk_start:chunk_end]

                # Prepare the binary message
                chunk_index_bytes = i.to_bytes(4, byteorder="little")
                total_chunks_bytes = total_body_chunks.to_bytes(4, byteorder="little")
                message = id_bytes + chunk_index_bytes + total_chunks_bytes + body_chunk
                await websocket.send(message)
                self.logger.debug(
                    f"Sent body chunk {i + 1}/{total_body_chunks} for ID: {request_id}"
                )
        else:
            self.logger.debug(f"No body to send for ID: {request_id}")

    async def shutdown(self):
        self.stop_event.set()
        tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
        if tasks:
            self.logger.debug(f"Cancelling {len(tasks)} outstanding tasks")
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
        await self.loop.shutdown_asyncgens()

    def run(self):
        try:
            self.loop.run_until_complete(self.connect())
        except KeyboardInterrupt:
            self.logger.debug("Received exit signal")
        finally:
            self.logger.debug("Shutting down...")
            self.loop.run_until_complete(self.shutdown())
            self.loop.close()
