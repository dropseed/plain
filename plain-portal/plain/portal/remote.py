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
import json
import os
import sys
import traceback
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime

from websockets.asyncio.client import ClientConnection
from websockets.asyncio.client import connect as ws_connect
from websockets.exceptions import ConnectionClosed

from .codegen import generate_code
from .crypto import PortalEncryptor, channel_id, perform_key_exchange
from .protocol import (
    DEFAULT_EXEC_TIMEOUT,
    DEFAULT_RELAY_HOST,
    FILE_CHUNK_SIZE,
    MAX_FILE_SIZE,
    chunk_count,
    make_error,
    make_exec_result,
    make_exec_stdout,
    make_file_data,
    make_file_push_result,
    make_ping,
    make_pong,
    make_relay_url,
)

_real_stdout = sys.stdout


def _log(msg: str) -> None:
    ts = datetime.now().strftime("%H:%M:%S")
    _real_stdout.write(f"[{ts}] {msg}\n")
    _real_stdout.flush()


async def _send_error(
    ws: ClientConnection,
    encryptor: PortalEncryptor,
    req_id: int | None,
    error_text: str,
) -> None:
    """Send an error response back through the tunnel."""
    msg = make_error(error_text)
    msg["_req_id"] = req_id
    await ws.send(encryptor.encrypt_message(msg))


class _TunnelWriter:
    """File-like that streams writes through the tunnel as exec_stdout messages."""

    def __init__(
        self,
        loop: asyncio.AbstractEventLoop,
        ws: ClientConnection,
        encryptor: PortalEncryptor,
        req_id: int | None,
    ) -> None:
        self._loop = loop
        self._ws = ws
        self._encryptor = encryptor
        self._req_id = req_id
        self._buffer = ""

    def write(self, s: str) -> int:
        self._buffer += s
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            self._send(line + "\n")
        return len(s)

    def flush(self) -> None:
        if self._buffer:
            self._send(self._buffer)
            self._buffer = ""

    def _send(self, data: str) -> None:
        msg = make_exec_stdout(data)
        msg["_req_id"] = self._req_id
        future = asyncio.run_coroutine_threadsafe(
            self._ws.send(self._encryptor.encrypt_message(msg)),
            self._loop,
        )
        try:
            future.result(timeout=30)
        except Exception:
            pass  # Don't crash exec for a send failure


async def run_remote(
    *,
    writable: bool = False,
    timeout_minutes: int = 30,
    relay_host: str = DEFAULT_RELAY_HOST,
) -> None:
    """Start the remote side of a portal session."""

    code = generate_code()

    mode = "writable" if writable else "read-only"
    print(f"Portal code: {code}")
    print(f"Session mode: {mode}")
    print("Waiting for connection...")
    print()

    cid = channel_id(code)
    relay_url = make_relay_url(relay_host, cid, "start")

    max_output = (
        1024 * 1024
    )  # 1MB — truncate return values to prevent massive relay payloads
    tmp_prefix = os.path.realpath("/tmp")  # Resolve once (macOS: /tmp → /private/tmp)

    def execute_code(
        code_str: str,
        *,
        json_output: bool = False,
        output_writer: _TunnelWriter,
    ) -> dict:
        """Execute Python code, streaming stdout through the tunnel.

        Each execution gets a fresh namespace. The last expression's value
        is captured as the return value (like the interactive REPL).
        """
        namespace: dict = {}
        return_value = None
        error = None

        try:
            tree = ast.parse(code_str, mode="exec")

            last_expr: ast.Expr | None = None
            if tree.body and isinstance(tree.body[-1], ast.Expr):
                popped = tree.body.pop()
                assert isinstance(popped, ast.Expr)
                last_expr = popped

            # Process-global redirect — safe because _log() uses _real_stdout
            ctx = contextlib.ExitStack()
            ctx.enter_context(redirect_stdout(output_writer))
            ctx.enter_context(redirect_stderr(output_writer))
            if not writable:
                try:
                    from plain.postgres.db import read_only

                    ctx.enter_context(read_only())
                except Exception:
                    pass  # No DB configured or plain-postgres not installed

            with ctx:
                if tree.body:
                    compiled = compile(tree, "<portal>", "exec")
                    exec(compiled, namespace)  # noqa: S102

                if last_expr is not None:
                    expr_code = compile(
                        ast.Expression(last_expr.value), "<portal>", "eval"
                    )
                    result = eval(expr_code, namespace)  # noqa: S307
                    if result is not None:
                        if json_output:
                            try:
                                return_value = json.dumps(result)
                            except (TypeError, ValueError):
                                return_value = repr(result)
                        else:
                            return_value = repr(result)

        except BaseException:
            error = traceback.format_exc()
        finally:
            # Flush any remaining buffered output
            output_writer.flush()
            # Close DB connection to prevent leaks across to_thread calls
            try:
                from plain.postgres.db import get_connection, has_connection

                if has_connection():
                    get_connection().close()
            except Exception:
                pass

        if return_value and len(return_value) > max_output:
            return_value = (
                return_value[:max_output]
                + f"\n... truncated ({len(return_value)} bytes total)"
            )

        return {
            "return_value": return_value,
            "error": error,
        }

    async def handle_file_pull(remote_path: str, req_id: int | None) -> None:
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
        except (PermissionError, IsADirectoryError, OSError) as e:
            await _send_error(ws, encryptor, req_id, f"{type(e).__name__}: {e}")

    async def handle_file_push(msg: dict) -> None:
        """Receive a file chunk and write it to disk."""
        req_id = msg.get("_req_id")
        remote_path = msg["remote_path"]
        chunk_idx = msg["chunk"]
        chunks = msg["chunks"]
        data = base64.b64decode(msg["data"])

        resolved = os.path.realpath(remote_path)
        if not resolved.startswith(tmp_prefix + "/"):
            await _send_error(
                ws,
                encryptor,
                req_id,
                f"Push restricted to /tmp/. Got: {remote_path} (resolved: {resolved})",
            )
            return

        if chunk_idx == 0:
            _log(f"push: {remote_path} ({chunks} chunks)")

        try:
            mode = "wb" if chunk_idx == 0 else "ab"
            with open(remote_path, mode) as f:
                f.write(data)
        except OSError as e:
            await _send_error(ws, encryptor, req_id, f"{type(e).__name__}: {e}")
            return

        # Ack every chunk so the sender doesn't block waiting
        if chunk_idx == chunks - 1:
            total_bytes = os.path.getsize(remote_path)
            _log(f"       received {total_bytes} bytes")
            result = make_file_push_result(path=remote_path, total_bytes=total_bytes)
        else:
            result = {"type": "file_push_ack", "chunk": chunk_idx}
        result["_req_id"] = req_id
        await ws.send(encryptor.encrypt_message(result))

    async with ws_connect(relay_url) as ws:
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

        async def send_keepalive_pings() -> None:
            while True:
                await asyncio.sleep(30)
                await ws.send(encryptor.encrypt_message(make_ping()))

        keepalive_task = asyncio.create_task(send_keepalive_pings())

        try:
            async for raw in ws:
                last_activity = asyncio.get_running_loop().time()

                if isinstance(raw, str):
                    continue

                msg = encryptor.decrypt_message(raw)
                msg_type = msg.get("type")

                if msg_type == "ping":
                    await ws.send(encryptor.encrypt_message(make_pong()))

                elif msg_type == "pong":
                    pass

                elif msg_type == "exec":
                    req_id = msg.get("_req_id")
                    code_str = msg["code"]
                    json_output = msg.get("json_output", False)
                    exec_timeout = msg.get("timeout", DEFAULT_EXEC_TIMEOUT)
                    _log(
                        f"exec: {code_str[:200]}{'...' if len(code_str) > 200 else ''}"
                    )
                    # Create a writer that streams stdout through the tunnel
                    tunnel_writer = _TunnelWriter(
                        asyncio.get_running_loop(), ws, encryptor, req_id
                    )
                    try:
                        result = await asyncio.wait_for(
                            asyncio.to_thread(
                                execute_code,
                                code_str,
                                json_output=json_output,
                                output_writer=tunnel_writer,
                            ),
                            timeout=exec_timeout,
                        )
                    except TimeoutError:
                        result = {
                            "return_value": None,
                            "error": f"Execution timed out ({exec_timeout} seconds). The code may still be running in the background.",
                        }
                    return_value = result.get("return_value")
                    error = result.get("error")
                    display = return_value or error or ""
                    if display:
                        _log(
                            f"       → {display[:200]}{'...' if len(display) > 200 else ''}"
                        )
                    # Send final result — stdout was already streamed
                    response = make_exec_result(
                        return_value=return_value,
                        error=error,
                    )
                    response["_req_id"] = req_id
                    await ws.send(encryptor.encrypt_message(response))

                elif msg_type == "file_pull":
                    req_id = msg.get("_req_id")
                    remote_path = msg["remote_path"]
                    _log(f"pull: {remote_path}")
                    await handle_file_pull(remote_path, req_id)

                elif msg_type == "file_push":
                    await handle_file_push(msg)

                else:
                    _log(f"Unknown message type: {msg_type}")

        except ConnectionClosed:
            pass  # Normal when relay or network drops the connection
        finally:
            timeout_task.cancel()
            keepalive_task.cancel()

    _log("Client disconnected.")
