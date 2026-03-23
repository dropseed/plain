"""Local side of a portal session.

Runs on the developer's machine. `connect` establishes the encrypted
tunnel through the relay and listens on a Unix socket. Subsequent
commands (exec, pull, push) talk to the connect process over the socket.
"""

from __future__ import annotations

import asyncio
import json
import os
import signal
import struct
import sys
import tempfile

import websockets.exceptions
from websockets.asyncio.client import connect as ws_connect

from .codegen import validate_code
from .crypto import channel_id, perform_key_exchange
from .protocol import (
    DEFAULT_RELAY_HOST,
    make_ping,
    make_relay_url,
)

SOCKET_PATH = os.path.join(tempfile.gettempdir(), "plain-portal.sock")


async def _send_framed(writer: asyncio.StreamWriter, data: bytes) -> None:
    """Write a length-prefixed message to a stream."""
    writer.write(struct.pack("!I", len(data)))
    writer.write(data)
    await writer.drain()


# 75MB — large enough for 50MB files base64-encoded (~67MB), prevents unbounded allocation
_MAX_FRAME_SIZE = 75 * 1024 * 1024


async def _recv_framed(reader: asyncio.StreamReader) -> bytes:
    """Read a length-prefixed message from a stream."""
    length_bytes = await reader.readexactly(4)
    length = struct.unpack("!I", length_bytes)[0]
    if length > _MAX_FRAME_SIZE:
        raise ValueError(f"Frame too large: {length} bytes (max {_MAX_FRAME_SIZE})")
    return await reader.readexactly(length)


async def connect(
    code: str,
    *,
    relay_host: str = DEFAULT_RELAY_HOST,
) -> None:
    """Connect to a remote portal session and run the daemon."""

    if not validate_code(code):
        print(f"Invalid portal code: {code}", file=sys.stderr)
        sys.exit(1)

    if os.path.exists(SOCKET_PATH):
        print(
            "A portal session is already active.",
            file=sys.stderr,
        )
        sys.exit(1)

    cid = channel_id(code)
    relay_url = make_relay_url(relay_host, cid, "connect")

    try:
        ws = await ws_connect(relay_url)
    except Exception as e:
        print(f"Failed to connect to relay: {e}", file=sys.stderr)
        sys.exit(1)

    encryptor = await perform_key_exchange(ws, code, side="connect")

    print("Connected to remote. Session active.")

    try:
        os.unlink(SOCKET_PATH)
    except FileNotFoundError:
        pass

    # Exec requests use queues (for streaming exec_stdout + exec_result).
    # All other request types use single-shot futures.
    pending_responses: dict[int, asyncio.Future] = {}
    pending_queues: dict[int, asyncio.Queue] = {}
    file_data_accumulators: dict[int, dict] = {}
    request_counter = 0

    async def handle_local_client(
        reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        """Handle a command from a local CLI invocation (exec/pull/push)."""
        nonlocal request_counter
        req_id = None
        is_exec = False

        try:
            data = await _recv_framed(reader)
            request = json.loads(data.decode("utf-8"))

            request_counter += 1
            req_id = request_counter
            request["_req_id"] = req_id
            is_exec = request.get("type") == "exec"

            if is_exec:
                # Exec uses a queue so we can stream exec_stdout messages
                queue: asyncio.Queue = asyncio.Queue()
                pending_queues[req_id] = queue
                await ws.send(encryptor.encrypt_message(request))

                # Read from the queue until we get the final exec_result
                exec_timeout = request.get("timeout", 120) + 30  # extra margin
                while True:
                    msg = await asyncio.wait_for(queue.get(), timeout=exec_timeout)
                    await _send_framed(writer, json.dumps(msg).encode("utf-8"))
                    if msg.get("type") != "exec_stdout":
                        break
            else:
                # Non-exec: single request/response via future
                future: asyncio.Future = asyncio.get_running_loop().create_future()
                pending_responses[req_id] = future
                await ws.send(encryptor.encrypt_message(request))
                response = await asyncio.wait_for(future, timeout=300)
                await _send_framed(writer, json.dumps(response).encode("utf-8"))

        except TimeoutError:
            await _send_framed(
                writer,
                json.dumps({"error": "Request timed out"}).encode("utf-8"),
            )
        except Exception as e:
            await _send_framed(writer, json.dumps({"error": str(e)}).encode("utf-8"))
        finally:
            if req_id is not None:
                pending_responses.pop(req_id, None)
                pending_queues.pop(req_id, None)
                file_data_accumulators.pop(req_id, None)
            writer.close()
            await writer.wait_closed()

    async def relay_listener() -> None:
        """Listen for messages from the remote side via WebSocket."""
        try:
            async for raw in ws:
                if isinstance(raw, str):
                    continue

                msg = encryptor.decrypt_message(raw)
                msg_type = msg.get("type")

                if msg_type == "ping":
                    await ws.send(encryptor.encrypt_message({"type": "pong"}))
                    continue

                if msg_type == "pong":
                    continue

                req_id = msg.pop("_req_id", None)
                if not req_id:
                    continue

                # Streaming exec messages go through the queue
                if msg_type in ("exec_stdout", "exec_result"):
                    if req_id in pending_queues:
                        await pending_queues[req_id].put(msg)
                    continue

                # File data accumulation (multiple chunks → single response)
                if msg_type == "file_data":
                    if req_id not in pending_responses:
                        continue
                    if req_id not in file_data_accumulators:
                        file_data_accumulators[req_id] = {
                            "name": msg["name"],
                            "chunks": msg["chunks"],
                            "received": {},
                        }
                    acc = file_data_accumulators[req_id]
                    acc["received"][msg["chunk"]] = msg["data"]
                    if len(acc["received"]) == acc["chunks"]:
                        all_data = "".join(
                            acc["received"][i] for i in range(acc["chunks"])
                        )
                        del file_data_accumulators[req_id]
                        pending_responses[req_id].set_result(
                            {
                                "type": "file_data",
                                "name": acc["name"],
                                "data": all_data,
                            }
                        )
                    continue

                # Everything else resolves the future directly
                if req_id in pending_responses:
                    pending_responses[req_id].set_result(msg)

        except websockets.exceptions.ConnectionClosed:
            pass
        finally:
            for future in pending_responses.values():
                if not future.done():
                    future.set_result({"error": "Remote disconnected"})
            for queue in pending_queues.values():
                await queue.put({"type": "error", "error": "Remote disconnected"})
            _cleanup()

    # Set restrictive umask so the socket is created owner-only (no TOCTOU window)
    old_umask = os.umask(0o177)
    try:
        server = await asyncio.start_unix_server(handle_local_client, path=SOCKET_PATH)
    finally:
        os.umask(old_umask)

    loop = asyncio.get_running_loop()

    def _handle_signal() -> None:
        _cleanup()
        loop.stop()

    loop.add_signal_handler(signal.SIGTERM, _handle_signal)
    loop.add_signal_handler(signal.SIGINT, _handle_signal)

    async def send_keepalive_pings() -> None:
        while True:
            await asyncio.sleep(30)
            await ws.send(encryptor.encrypt_message(make_ping()))

    keepalive_task = asyncio.create_task(send_keepalive_pings())

    try:
        await relay_listener()
    finally:
        keepalive_task.cancel()
        server.close()
        await server.wait_closed()
        _cleanup()


def _cleanup() -> None:
    """Remove the socket file."""
    try:
        os.unlink(SOCKET_PATH)
    except FileNotFoundError:
        pass


async def send_command(request: dict) -> dict:
    """Send a command to the connect process via Unix socket.

    Returns a single response. For streaming exec, use send_exec_streaming instead.
    """
    try:
        reader, writer = await asyncio.open_unix_connection(SOCKET_PATH)
    except (FileNotFoundError, ConnectionRefusedError):
        print(
            "No active portal session. Run 'plain portal connect <code>' first.",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        await _send_framed(writer, json.dumps(request).encode("utf-8"))
        response_data = await _recv_framed(reader)
        return json.loads(response_data.decode("utf-8"))
    finally:
        writer.close()
        await writer.wait_closed()


async def send_exec_streaming(
    request: dict,
    on_stdout: callable,  # type: ignore[type-arg]
) -> dict:
    """Send an exec request and stream stdout chunks as they arrive.

    Calls on_stdout(data) for each exec_stdout chunk.
    Returns the final exec_result response.
    """
    try:
        reader, writer = await asyncio.open_unix_connection(SOCKET_PATH)
    except (FileNotFoundError, ConnectionRefusedError):
        print(
            "No active portal session. Run 'plain portal connect <code>' first.",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        await _send_framed(writer, json.dumps(request).encode("utf-8"))
        while True:
            response_data = await _recv_framed(reader)
            msg = json.loads(response_data.decode("utf-8"))
            if msg.get("type") == "exec_stdout":
                on_stdout(msg["data"])
            else:
                return msg
    finally:
        writer.close()
        await writer.wait_closed()
