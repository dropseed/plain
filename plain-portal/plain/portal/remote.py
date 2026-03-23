"""Remote side of a portal session.

Runs on the production machine. Connects to the relay, prints a portal
code, waits for the local side to connect, then executes commands as
they arrive through the encrypted tunnel.
"""

from __future__ import annotations

import ast
import asyncio
import base64
import contextlib
import io
import os
import traceback
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime

import websockets.client

from .codegen import generate_code
from .crypto import PortalEncryptor, channel_id, perform_key_exchange
from .protocol import (
    DEFAULT_RELAY_HOST,
    FILE_CHUNK_SIZE,
    MAX_FILE_SIZE,
    chunk_count,
    make_error,
    make_exec_result,
    make_file_data,
    make_file_push_result,
    make_pong,
    make_relay_url,
)


def _log(msg: str) -> None:
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def _truncate(s: str, max_len: int = 200) -> str:
    if len(s) <= max_len:
        return s
    return s[:max_len] + "..."


async def _send_error(
    ws: websockets.client.ClientConnection,
    encryptor: PortalEncryptor,
    req_id: int | None,
    error_text: str,
) -> None:
    """Send an error response back through the tunnel."""
    msg = make_error(error_text)
    msg["_req_id"] = req_id
    await ws.send(encryptor.encrypt_message(msg))


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

    # Set up Plain runtime once at session start
    try:
        import plain.runtime

        plain.runtime.setup()
    except Exception:
        pass

    mode = "writable" if writable else "read-only"
    print(f"Portal code: {code}")
    print(f"Session mode: {mode}")
    print("Waiting for connection...")
    print()

    cid = channel_id(code)
    relay_url = make_relay_url(relay_host, cid, "start")

    async with websockets.client.connect(relay_url) as ws:
        encryptor = await perform_key_exchange(ws, code, side="start")
        _log("Connected from remote client.")

        last_activity = asyncio.get_running_loop().time()

        async def check_timeout() -> None:
            nonlocal last_activity
            if timeout_minutes <= 0:
                return
            while True:
                await asyncio.sleep(60)
                idle = asyncio.get_running_loop().time() - last_activity
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
                last_activity = asyncio.get_running_loop().time()

                if isinstance(raw, str):
                    continue

                msg = encryptor.decrypt_message(raw)
                msg_type = msg.get("type")

                if msg_type == "ping":
                    await ws.send(encryptor.encrypt_message(make_pong()))

                elif msg_type == "exec":
                    req_id = msg.get("_req_id")
                    code_str = msg["code"]
                    _log(f"exec: {_truncate(code_str)}")
                    # Run in thread to avoid blocking the async loop
                    result = await asyncio.to_thread(
                        _execute_code, code_str, writable=writable
                    )
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
                    if not writable:
                        req_id = msg.get("_req_id")
                        await _send_error(
                            ws,
                            encryptor,
                            req_id,
                            "File push requires --writable mode",
                        )
                    else:
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

    When ``writable`` is False (default), the database connection is set
    to read-only mode so INSERT/UPDATE/DELETE/DDL raise ReadOnlyError.
    """
    namespace: dict = {}
    stdout_capture = io.StringIO()
    stderr_capture = io.StringIO()
    return_value = None
    error = None

    try:
        tree = ast.parse(code_str, mode="exec")
        last_expr = None

        if tree.body and isinstance(tree.body[-1], ast.Expr):
            last_expr = tree.body.pop()

        # Build the execution context — enforce read-only unless --writable
        ctx = contextlib.ExitStack()
        ctx.enter_context(redirect_stdout(stdout_capture))
        ctx.enter_context(redirect_stderr(stderr_capture))
        if not writable:
            try:
                from plain.postgres.connections import read_only

                ctx.enter_context(read_only())
            except Exception:
                pass  # No DB configured or plain-postgres not installed

        with ctx:
            if tree.body:
                compiled = compile(tree, "<portal>", "exec")
                exec(compiled, namespace)  # noqa: S102

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
            await _send_error(
                ws,
                encryptor,
                req_id,
                f"File too large: {file_size} bytes (max {MAX_FILE_SIZE})",
            )
            return

        name = os.path.basename(remote_path)
        chunks = chunk_count(file_size)

        _log(f"       sending {name} ({file_size} bytes, {chunks} chunks)")

        with open(remote_path, "rb") as f:
            for i in range(chunks):
                data = f.read(FILE_CHUNK_SIZE)
                msg = make_file_data(name=name, chunk=i, chunks=chunks, data=data)
                msg["_req_id"] = req_id
                await ws.send(encryptor.encrypt_message(msg))

    except FileNotFoundError:
        await _send_error(ws, encryptor, req_id, f"File not found: {remote_path}")
    except PermissionError:
        await _send_error(ws, encryptor, req_id, f"Permission denied: {remote_path}")


async def _handle_file_push(
    ws: websockets.client.ClientConnection,
    encryptor: PortalEncryptor,
    msg: dict,
) -> None:
    """Receive a file chunk and write it to disk."""
    req_id = msg.get("_req_id")
    remote_path = msg["remote_path"]
    chunk_idx = msg["chunk"]
    chunks = msg["chunks"]
    data = base64.b64decode(msg["data"])

    # Security: resolve symlinks and .. components, then verify still under /tmp/
    resolved = os.path.realpath(remote_path)
    if not resolved.startswith("/tmp/"):
        await _send_error(
            ws,
            encryptor,
            req_id,
            f"Push restricted to /tmp/. Got: {remote_path} (resolved: {resolved})",
        )
        return

    if chunk_idx == 0:
        _log(f"push: {remote_path} ({chunks} chunks)")

    mode = "wb" if chunk_idx == 0 else "ab"
    with open(remote_path, mode) as f:
        f.write(data)

    if chunk_idx == chunks - 1:
        total_bytes = os.path.getsize(remote_path)
        _log(f"       received {total_bytes} bytes")
        result = make_file_push_result(path=remote_path, total_bytes=total_bytes)
        result["_req_id"] = req_id
        await ws.send(encryptor.encrypt_message(result))
