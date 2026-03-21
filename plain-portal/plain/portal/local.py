"""Local side of a portal session.

Runs on the developer's machine. `connect` establishes the encrypted
tunnel through the relay and starts a background process that listens
on a Unix socket. Subsequent commands (exec, pull, push) talk to
the background process over the socket.
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import signal
import struct
import sys
import tempfile

import websockets.client

from .codegen import validate_code
from .crypto import PortalEncryptor, channel_id, create_spake2_joiner
from .protocol import (
    DEFAULT_RELAY_HOST,
    PROTOCOL_VERSION,
    RELAY_PATH,
)

SOCKET_PATH = os.path.join(tempfile.gettempdir(), "plain-portal.sock")
PID_PATH = os.path.join(tempfile.gettempdir(), "plain-portal.pid")


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

    # Check for existing session
    if os.path.exists(SOCKET_PATH):
        print(
            "A portal session is already active. Run 'plain portal disconnect' first.",
            file=sys.stderr,
        )
        sys.exit(1)

    scheme = "ws" if relay_host.startswith("localhost") else "wss"
    cid = channel_id(code)
    relay_url = f"{scheme}://{relay_host}{RELAY_PATH}?v={PROTOCOL_VERSION}&channel={cid}&side=connect"

    # SPAKE2 side B (joiner)
    spake = create_spake2_joiner(code)
    spake_msg = spake.msg()

    try:
        ws = await websockets.client.connect(relay_url)
    except Exception as e:
        print(f"Failed to connect to relay: {e}", file=sys.stderr)
        sys.exit(1)

    # Send our SPAKE2 message
    await ws.send(base64.b64encode(spake_msg).decode("ascii"))

    # Receive peer's SPAKE2 message
    peer_msg_b64 = await ws.recv()
    peer_msg = base64.b64decode(peer_msg_b64)
    key = spake.finish(peer_msg)

    encryptor = PortalEncryptor(key)

    print("Connected to remote. Session active.")

    if not foreground:
        # Fork into background
        pid = os.fork()
        if pid > 0:
            # Parent — save PID and exit
            with open(PID_PATH, "w") as f:
                f.write(str(pid))
            return
        # Child continues as daemon
        os.setsid()

    # Write PID for foreground mode too
    if foreground:
        with open(PID_PATH, "w") as f:
            f.write(str(os.getpid()))

    # Set up Unix socket server
    await _run_daemon(ws, encryptor)


async def _run_daemon(
    ws: websockets.client.ClientConnection,
    encryptor: PortalEncryptor,
) -> None:
    """Run the background daemon that bridges Unix socket ↔ WebSocket."""

    # Clean up stale socket
    if os.path.exists(SOCKET_PATH):
        os.unlink(SOCKET_PATH)

    pending_responses: dict[int, asyncio.Future] = {}
    # Accumulate multi-chunk file_data responses before delivering
    file_data_accumulators: dict[int, dict] = {}
    request_counter = 0

    async def handle_local_client(
        reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        """Handle a command from a local CLI invocation (exec/pull/push)."""
        nonlocal request_counter

        try:
            # Read length-prefixed request
            length_bytes = await reader.readexactly(4)
            length = struct.unpack("!I", length_bytes)[0]
            data = await reader.readexactly(length)
            request = json.loads(data.decode("utf-8"))

            # Tag with a request ID so we can match responses
            request_counter += 1
            req_id = request_counter
            request["_req_id"] = req_id

            # Send encrypted through WebSocket
            encrypted = encryptor.encrypt_message(request)
            await ws.send(encrypted)

            # Wait for response
            future: asyncio.Future = asyncio.get_event_loop().create_future()
            pending_responses[req_id] = future

            response = await asyncio.wait_for(future, timeout=300)

            # Send response back to local CLI
            response_bytes = json.dumps(response).encode("utf-8")
            writer.write(struct.pack("!I", len(response_bytes)))
            writer.write(response_bytes)
            await writer.drain()

        except TimeoutError:
            error = json.dumps({"error": "Request timed out (5 minutes)"}).encode(
                "utf-8"
            )
            writer.write(struct.pack("!I", len(error)))
            writer.write(error)
            await writer.drain()
        except Exception as e:
            error = json.dumps({"error": str(e)}).encode("utf-8")
            writer.write(struct.pack("!I", len(error)))
            writer.write(error)
            await writer.drain()
        finally:
            pending_responses.pop(req_id, None)
            writer.close()
            await writer.wait_closed()

    async def relay_listener() -> None:
        """Listen for messages from the remote side via WebSocket."""
        try:
            async for raw in ws:
                if isinstance(raw, str):
                    # Shouldn't happen after key exchange
                    continue

                msg = encryptor.decrypt_message(raw)
                msg_type = msg.get("type")

                if msg_type == "ping":
                    await ws.send(encryptor.encrypt_message({"type": "pong"}))
                    continue

                # Match response to pending request
                req_id = msg.pop("_req_id", None)
                if not req_id or req_id not in pending_responses:
                    continue

                if msg_type == "file_data":
                    # Accumulate chunks, deliver when all received
                    if req_id not in file_data_accumulators:
                        file_data_accumulators[req_id] = {
                            "name": msg["name"],
                            "chunks": msg["chunks"],
                            "received": {},
                        }
                    acc = file_data_accumulators[req_id]
                    acc["received"][msg["chunk"]] = msg["data"]
                    if len(acc["received"]) == acc["chunks"]:
                        # All chunks received — concatenate and deliver
                        all_data = ""
                        for i in range(acc["chunks"]):
                            all_data += acc["received"][i]
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
            # Signal all pending requests that connection is gone
            for future in pending_responses.values():
                if not future.done():
                    future.set_result({"error": "Remote disconnected"})
            _cleanup()

    server = await asyncio.start_unix_server(handle_local_client, path=SOCKET_PATH)

    # Restrict socket to current user only (default is world-accessible)
    os.chmod(SOCKET_PATH, 0o600)

    # Handle SIGTERM for clean shutdown
    loop = asyncio.get_event_loop()

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
        # Send length-prefixed request
        data = json.dumps(request).encode("utf-8")
        writer.write(struct.pack("!I", len(data)))
        writer.write(data)
        await writer.drain()

        # Read length-prefixed response
        length_bytes = await reader.readexactly(4)
        length = struct.unpack("!I", length_bytes)[0]
        response_data = await reader.readexactly(length)
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
            # Check if process is alive
            os.kill(pid, 0)
            print(f"Portal session active (PID {pid})")
            print(f"Socket: {SOCKET_PATH}")
        except (ProcessLookupError, ValueError):
            print("Portal daemon not running (stale PID file).")
            _cleanup()
    else:
        print("No active portal session.")
