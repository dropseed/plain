"""Remote side of a portal session.

Runs on the production machine. Connects to the relay, prints a portal
code, waits for the local side to connect, then executes commands as
they arrive through the encrypted tunnel.
"""

from __future__ import annotations

import ast
import asyncio
import base64
import io
import os
import traceback
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime

import websockets.client

from .codegen import generate_code
from .crypto import PortalEncryptor, channel_id, create_spake2_initiator
from .protocol import (
    DEFAULT_RELAY_HOST,
    FILE_CHUNK_SIZE,
    MAX_FILE_SIZE,
    PROTOCOL_VERSION,
    RELAY_PATH,
    make_exec_result,
    make_file_data,
    make_file_push_result,
    make_pong,
)


def _log(msg: str) -> None:
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def _truncate(s: str, max_len: int = 200) -> str:
    if len(s) <= max_len:
        return s
    return s[:max_len] + "..."


async def run_remote(
    *,
    code: str | None = None,
    writable: bool = False,
    timeout_minutes: int = 30,
    relay_host: str = DEFAULT_RELAY_HOST,
) -> None:
    """Start the remote side of a portal session."""

    if code is None:
        code = generate_code()

    print(f"Portal code: {code}")
    print("Waiting for connection...")
    print()

    # Build relay URL
    scheme = "ws" if relay_host.startswith("localhost") else "wss"
    cid = channel_id(code)
    relay_url = f"{scheme}://{relay_host}{RELAY_PATH}?v={PROTOCOL_VERSION}&channel={cid}&side=start"

    # SPAKE2 side A (initiator)
    spake = create_spake2_initiator(code)
    spake_msg = spake.msg()

    async with websockets.client.connect(relay_url) as ws:
        # Send our SPAKE2 message as the first thing
        await ws.send(base64.b64encode(spake_msg).decode("ascii"))

        # Wait for the other side's SPAKE2 message
        peer_msg_b64 = await ws.recv()
        peer_msg = base64.b64decode(peer_msg_b64)
        key = spake.finish(peer_msg)

        encryptor = PortalEncryptor(key)
        _log("Connected from remote client.")

        # Main message loop
        last_activity = asyncio.get_event_loop().time()

        async def check_timeout() -> None:
            nonlocal last_activity
            if timeout_minutes <= 0:
                return
            while True:
                await asyncio.sleep(60)
                idle = asyncio.get_event_loop().time() - last_activity
                remaining = (timeout_minutes * 60) - idle
                if remaining <= 60 and remaining > 0:
                    print(
                        f"\nWarning: session will timeout in {int(remaining)} seconds due to inactivity.",
                        flush=True,
                    )
                if idle >= timeout_minutes * 60:
                    print(
                        "\nSession timed out due to inactivity.",
                        flush=True,
                    )
                    await ws.close()
                    return

        timeout_task = asyncio.create_task(check_timeout())

        try:
            async for raw in ws:
                last_activity = asyncio.get_event_loop().time()

                if isinstance(raw, str):
                    # Shouldn't happen after key exchange — ignore
                    continue

                msg = encryptor.decrypt_message(raw)
                msg_type = msg.get("type")

                if msg_type == "ping":
                    await ws.send(encryptor.encrypt_message(make_pong()))

                elif msg_type == "exec":
                    req_id = msg.get("_req_id")
                    code_str = msg["code"]
                    _log(f"exec: {_truncate(code_str)}")
                    result = _execute_code(code_str, writable=writable)
                    display = result.get("return_value") or result.get("error") or ""
                    if display:
                        _log(f"       → {_truncate(display)}")
                    response = make_exec_result(
                        stdout=result["stdout"],
                        return_value=result["return_value"],
                        error=result["error"],
                    )
                    response["_req_id"] = req_id
                    await ws.send(encryptor.encrypt_message(response))

                elif msg_type == "file_pull":
                    req_id = msg.get("_req_id")
                    remote_path = msg["remote_path"]
                    _log(f"pull: {remote_path}")
                    await _handle_file_pull(ws, encryptor, remote_path, req_id)

                elif msg_type == "file_push":
                    await _handle_file_push(ws, encryptor, msg)

                else:
                    _log(f"Unknown message type: {msg_type}")

        finally:
            timeout_task.cancel()

    _log("Client disconnected.")


def _execute_code(code_str: str, *, writable: bool = False) -> dict:
    """Execute Python code and capture stdout/stderr + return value.

    Each execution gets a fresh namespace. The last expression's value
    is captured as the return value (like the interactive REPL).
    """
    namespace: dict = {}

    # Set up Plain runtime so models etc. are available
    try:
        import plain.runtime

        plain.runtime.setup()
    except Exception:
        pass  # May already be set up, or not available

    stdout_capture = io.StringIO()
    stderr_capture = io.StringIO()
    return_value = None
    error = None

    try:
        # Parse the code to separate the last expression (if any)
        tree = ast.parse(code_str, mode="exec")
        last_expr = None

        if tree.body and isinstance(tree.body[-1], ast.Expr):
            last_expr = tree.body.pop()

        with redirect_stdout(stdout_capture), redirect_stderr(stderr_capture):
            # Execute all statements
            if tree.body:
                compiled = compile(tree, "<portal>", "exec")
                exec(compiled, namespace)  # noqa: S102

            # Evaluate the last expression for its value
            if last_expr is not None:
                expr_code = compile(ast.Expression(last_expr.value), "<portal>", "eval")
                result = eval(expr_code, namespace)  # noqa: S307
                if result is not None:
                    return_value = repr(result)

    except Exception:
        error = traceback.format_exc()

    stdout = stdout_capture.getvalue() + stderr_capture.getvalue()

    return {
        "stdout": stdout,
        "return_value": return_value,
        "error": error,
    }


async def _handle_file_pull(
    ws: websockets.client.ClientConnection,
    encryptor: PortalEncryptor,
    remote_path: str,
    req_id: int | None,
) -> None:
    """Read a file from disk and send it in chunks."""
    try:
        file_size = os.path.getsize(remote_path)
        if file_size > MAX_FILE_SIZE:
            error_msg = make_exec_result(
                stdout="",
                return_value=None,
                error=f"File too large: {file_size} bytes (max {MAX_FILE_SIZE})",
            )
            error_msg["_req_id"] = req_id
            await ws.send(encryptor.encrypt_message(error_msg))
            return

        name = os.path.basename(remote_path)
        chunks = max(1, (file_size + FILE_CHUNK_SIZE - 1) // FILE_CHUNK_SIZE)

        _log(f"       sending {name} ({file_size} bytes, {chunks} chunks)")

        with open(remote_path, "rb") as f:
            for i in range(chunks):
                data = f.read(FILE_CHUNK_SIZE)
                msg = make_file_data(name=name, chunk=i, chunks=chunks, data=data)
                msg["_req_id"] = req_id
                await ws.send(encryptor.encrypt_message(msg))

    except FileNotFoundError:
        error_msg = make_exec_result(
            stdout="", return_value=None, error=f"File not found: {remote_path}"
        )
        error_msg["_req_id"] = req_id
        await ws.send(encryptor.encrypt_message(error_msg))
    except PermissionError:
        error_msg = make_exec_result(
            stdout="",
            return_value=None,
            error=f"Permission denied: {remote_path}",
        )
        error_msg["_req_id"] = req_id
        await ws.send(encryptor.encrypt_message(error_msg))


async def _handle_file_push(
    ws: websockets.client.ClientConnection,
    encryptor: PortalEncryptor,
    msg: dict,
) -> None:
    """Receive a file chunk and write it to disk."""
    req_id = msg.get("_req_id")
    remote_path = msg["remote_path"]
    chunk = msg["chunk"]
    chunks = msg["chunks"]
    data = base64.b64decode(msg["data"])

    # Security: resolve symlinks and .. components, then verify still under /tmp/
    resolved = os.path.realpath(remote_path)
    if not resolved.startswith("/tmp/"):
        error_msg = make_exec_result(
            stdout="",
            return_value=None,
            error=f"Push restricted to /tmp/. Got: {remote_path} (resolved: {resolved})",
        )
        error_msg["_req_id"] = req_id
        await ws.send(encryptor.encrypt_message(error_msg))
        return

    if chunk == 0:
        _log(f"push: {remote_path} ({chunks} chunks)")

    # Write/append the chunk
    mode = "wb" if chunk == 0 else "ab"
    with open(remote_path, mode) as f:
        f.write(data)

    # Send confirmation after last chunk
    if chunk == chunks - 1:
        total_bytes = os.path.getsize(remote_path)
        _log(f"       received {total_bytes} bytes")
        result = make_file_push_result(path=remote_path, total_bytes=total_bytes)
        result["_req_id"] = req_id
        await ws.send(encryptor.encrypt_message(result))
