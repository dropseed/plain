"""Local side of a portal session.

Runs on the developer's machine. `connect` spawns a background daemon that
establishes the encrypted tunnel through the relay and listens on a Unix
socket. Subsequent commands (exec, pull, push) talk to the daemon over the
socket, and `disconnect` stops it.
"""

from __future__ import annotations

import asyncio
import fcntl
import functools
import hashlib
import json
import os
import signal
import struct
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable

import websockets.exceptions
from websockets.asyncio.client import connect as ws_connect

from .codegen import validate_code
from .crypto import channel_id, perform_key_exchange
from .protocol import (
    DEFAULT_RELAY_HOST,
    make_ping,
    make_relay_url,
)


@functools.lru_cache
def _portal_dir() -> str:
    """Return .plain/portal/ in the project root, creating it if needed."""
    from plain.runtime import PLAIN_TEMP_PATH

    d = os.path.join(PLAIN_TEMP_PATH, "portal")
    os.makedirs(d, exist_ok=True)
    return d


def _socket_path() -> str:
    """Unix socket path, kept short and project-scoped.

    AF_UNIX paths are limited to ~104 bytes on macOS, so the socket can't
    live under the project's .plain/ directory -- a deep checkout path
    fails with "AF_UNIX path too long".  Hash the project dir into the
    system temp dir instead.
    """
    project_hash = hashlib.sha256(_portal_dir().encode()).hexdigest()[:12]
    return os.path.join(tempfile.gettempdir(), f"plain-portal-{project_hash}.sock")


def _lock_path() -> str:
    """The daemon holds an exclusive flock on this file for its lifetime and
    records its pid in it.  Liveness comes from the lock (the kernel drops it
    on crash), identity from the contents -- so a stale pid is never signalled."""
    return os.path.join(_portal_dir(), "portal.lock")


def _log_path() -> str:
    return os.path.join(_portal_dir(), "connect.log")


# The daemon prints this once the Unix socket is listening.  `connect` waits
# for it in the log to know the session is ready.
_SESSION_ACTIVE_LINE = "Connected to remote. Session active."

# How long `connect` waits for the daemon to reach the relay and open its socket
_DAEMON_STARTUP_TIMEOUT = 30

_lock_fd: int | None = None


def _acquire_lock() -> bool:
    """Claim the session lock for this process's lifetime, recording our pid.

    Returns False if another live daemon holds it.
    """
    global _lock_fd
    fd = os.open(_lock_path(), os.O_CREAT | os.O_RDWR, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        os.close(fd)
        return False
    os.ftruncate(fd, 0)
    os.write(fd, str(os.getpid()).encode())
    _lock_fd = fd  # Held open until process exit.
    return True


def _live_daemon_pid() -> int | None:
    """Return the pid of the daemon holding the lock, or None if nobody does."""
    try:
        fd = os.open(_lock_path(), os.O_RDONLY)
    except FileNotFoundError:
        return None
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        # Locked -- a daemon is alive and its pid is in the file.
        contents = os.read(fd, 32).decode().strip()
        return int(contents) if contents else None
    else:
        # We got the lock, so no daemon holds it.  Drop it again.
        return None
    finally:
        os.close(fd)


def spawn_connect_daemon(code: str, *, relay_host: str) -> None:
    """Run `connect --foreground` as a detached background process.

    Returns once the daemon reports the session is active, so callers can
    go straight to `exec`/`pull`/`push`. Exits non-zero (with the daemon's
    output) if it fails to connect for any reason -- bad code, relay down,
    session already active.

    This is a spawn, not a fork -- os.fork() after the interpreter is up
    crashes on macOS (ObjC runtime fork safety).
    """
    log_path = _log_path()
    with open(log_path, "w") as log:
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "plain",
                "portal",
                "connect",
                "--foreground",
                "--relay-host",
                relay_host,
                code,
            ],
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )

    deadline = time.monotonic() + _DAEMON_STARTUP_TIMEOUT
    while time.monotonic() < deadline:
        with open(log_path) as log:
            output = log.read()
        if _SESSION_ACTIVE_LINE in output:
            print(_SESSION_ACTIVE_LINE)
            return
        if process.poll() is not None:
            break
        time.sleep(0.1)
    else:
        process.terminate()

    # The daemon exited or never came up -- surface whatever it printed.
    with open(log_path) as log:
        output = log.read().strip()
    print(output or "Portal connect failed to start.", file=sys.stderr)
    sys.exit(1)


def disconnect_daemon() -> None:
    """Stop the background connect process, if there is one."""
    pid = _live_daemon_pid()
    if pid is None:
        print("No active portal session.")
        return

    os.kill(pid, signal.SIGTERM)

    # The lock is released when the daemon exits.
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if _live_daemon_pid() is None:
            break
        time.sleep(0.1)
    else:
        os.kill(pid, signal.SIGKILL)

    _cleanup()
    print("Portal session disconnected.")


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

    if not _acquire_lock():
        print("A portal session is already active.", file=sys.stderr)
        sys.exit(1)

    # Clean up any stale socket from a previous crash.
    _cleanup()

    cid = channel_id(code)
    relay_url = make_relay_url(relay_host, cid, "connect")

    try:
        ws = await ws_connect(relay_url)
    except Exception as e:
        print(f"Failed to connect to relay: {e}", file=sys.stderr)
        sys.exit(1)

    encryptor = await perform_key_exchange(ws, code, side="connect")

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
        server = await asyncio.start_unix_server(
            handle_local_client, path=_socket_path()
        )
    finally:
        os.umask(old_umask)

    print(_SESSION_ACTIVE_LINE, flush=True)

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
    """Remove the socket file.  The lock file is left in place — the flock
    is on the inode, so unlinking it would let a new process acquire a
    lock on a different inode."""
    try:
        os.unlink(_socket_path())
    except FileNotFoundError:
        pass


async def send_command(request: dict) -> dict:
    """Send a command to the connect process via Unix socket.

    Returns a single response. For streaming exec, use send_exec_streaming instead.
    """
    try:
        reader, writer = await asyncio.open_unix_connection(_socket_path())
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
    on_stdout: Callable[[str], None],
) -> dict:
    """Send an exec request and stream stdout chunks as they arrive.

    Calls on_stdout(data) for each exec_stdout chunk.
    Returns the final exec_result response.
    """
    try:
        reader, writer = await asyncio.open_unix_connection(_socket_path())
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
