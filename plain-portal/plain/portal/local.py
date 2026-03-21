"""Local side of a portal session.

Runs on the developer's machine. `connect` establishes the encrypted
tunnel through the relay and starts a background process that listens
on a Unix socket. Subsequent commands (exec, pull, push) talk to
the background process over the socket.
"""

from __future__ import annotations

import asyncio
import json
import os
import signal
import struct
import sys
import tempfile

import websockets.client
import websockets.exceptions

from .codegen import validate_code
from .crypto import PortalEncryptor, channel_id, perform_key_exchange
from .protocol import (
    DEFAULT_RELAY_HOST,
    make_relay_url,
)

SOCKET_PATH = os.path.join(tempfile.gettempdir(), "plain-portal.sock")
PID_PATH = os.path.join(tempfile.gettempdir(), "plain-portal.pid")


async def _send_framed(writer: asyncio.StreamWriter, data: bytes) -> None:
    """Write a length-prefixed message to a stream."""
    writer.write(struct.pack("!I", len(data)))
    writer.write(data)
    await writer.drain()


# 10MB — generous for JSON messages, prevents unbounded allocation
_MAX_FRAME_SIZE = 10 * 1024 * 1024


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
    foreground: bool = False,
) -> None:
    """Connect to a remote portal session and start the local daemon."""

    if not validate_code(code):
        print(f"Invalid portal code: {code}", file=sys.stderr)
        sys.exit(1)

    if os.path.exists(SOCKET_PATH):
        print(
            "A portal session is already active. Run 'plain portal disconnect' first.",
            file=sys.stderr,
        )
        sys.exit(1)

    cid = channel_id(code)
    relay_url = make_relay_url(relay_host, cid, "connect")

    try:
        ws = await websockets.client.connect(relay_url)
    except Exception as e:
        print(f"Failed to connect to relay: {e}", file=sys.stderr)
        sys.exit(1)

    encryptor = await perform_key_exchange(ws, code, side="connect")

    print("Connected to remote. Session active.")

    if not foreground:
        pid = os.fork()
        if pid > 0:
            with open(PID_PATH, "w") as f:
                f.write(str(pid))
            return
        os.setsid()

    if foreground:
        with open(PID_PATH, "w") as f:
            f.write(str(os.getpid()))

    await _run_daemon(ws, encryptor)


async def _run_daemon(
    ws: websockets.client.ClientConnection,
    encryptor: PortalEncryptor,
) -> None:
    """Run the background daemon that bridges Unix socket and WebSocket."""

    try:
        os.unlink(SOCKET_PATH)
    except FileNotFoundError:
        pass

    pending_responses: dict[int, asyncio.Future] = {}
    file_data_accumulators: dict[int, dict] = {}
    request_counter = 0

    async def handle_local_client(
        reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        """Handle a command from a local CLI invocation (exec/pull/push)."""
        nonlocal request_counter
        req_id = None

        try:
            data = await _recv_framed(reader)
            request = json.loads(data.decode("utf-8"))

            request_counter += 1
            req_id = request_counter
            request["_req_id"] = req_id

            await ws.send(encryptor.encrypt_message(request))

            future: asyncio.Future = asyncio.get_running_loop().create_future()
            pending_responses[req_id] = future

            response = await asyncio.wait_for(future, timeout=300)

            await _send_framed(writer, json.dumps(response).encode("utf-8"))

        except TimeoutError:
            await _send_framed(
                writer,
                json.dumps({"error": "Request timed out (5 minutes)"}).encode("utf-8"),
            )
        except Exception as e:
            await _send_framed(writer, json.dumps({"error": str(e)}).encode("utf-8"))
        finally:
            if req_id is not None:
                pending_responses.pop(req_id, None)
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

                req_id = msg.pop("_req_id", None)
                if not req_id or req_id not in pending_responses:
                    continue

                if msg_type == "file_data":
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
                else:
                    pending_responses[req_id].set_result(msg)

        except websockets.exceptions.ConnectionClosed:
            pass
        finally:
            for future in pending_responses.values():
                if not future.done():
                    future.set_result({"error": "Remote disconnected"})
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

    try:
        await relay_listener()
    finally:
        server.close()
        await server.wait_closed()
        _cleanup()


def _cleanup() -> None:
    """Remove socket and PID files."""
    for path in (SOCKET_PATH, PID_PATH):
        try:
            os.unlink(path)
        except FileNotFoundError:
            pass


async def send_command(request: dict) -> dict:
    """Send a command to the background daemon via Unix socket."""
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


def disconnect() -> None:
    """Kill the background daemon and clean up."""
    if os.path.exists(PID_PATH):
        try:
            with open(PID_PATH) as f:
                pid = int(f.read().strip())
            os.kill(pid, signal.SIGTERM)
            print("Portal session disconnected.")
        except (ProcessLookupError, ValueError):
            print("Portal daemon not running (stale PID file).")
        _cleanup()
    elif os.path.exists(SOCKET_PATH):
        _cleanup()
        print("Cleaned up stale socket.")
    else:
        print("No active portal session.")


def status() -> None:
    """Show portal session status."""
    if os.path.exists(PID_PATH):
        try:
            with open(PID_PATH) as f:
                pid = int(f.read().strip())
            os.kill(pid, 0)
            print(f"Portal session active (PID {pid})")
            print(f"Socket: {SOCKET_PATH}")
        except (ProcessLookupError, ValueError):
            print("Portal daemon not running (stale PID file).")
            _cleanup()
    else:
        print("No active portal session.")
