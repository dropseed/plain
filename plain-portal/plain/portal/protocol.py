"""Message protocol for portal communication.

Messages are JSON dicts encrypted with NaCl before being sent through
the relay. The relay only sees opaque bytes.

Message types:
  exec           - Execute Python code (local → remote)
  exec_stdout    - Streaming stdout chunk (remote → local)
  exec_result    - Execution result (remote → local)
  error          - Error response (remote → local)
  file_pull      - Request a file (local → remote)
  file_data      - File contents chunk (remote → local)
  file_push      - Send a file chunk (local → remote)
  file_push_result - File push confirmation (remote → local)
  ping           - Keepalive (either direction)
  pong           - Keepalive response (either direction)
"""

from __future__ import annotations

import base64
import math

# Max chunk size for file transfers (256KB).
FILE_CHUNK_SIZE = 256 * 1024

# Max file size for transfers (50MB).
MAX_FILE_SIZE = 50 * 1024 * 1024

# Default exec timeout in seconds.
DEFAULT_EXEC_TIMEOUT = 120

# Relay WebSocket endpoint.
DEFAULT_RELAY_HOST = "portal.plainframework.com"
RELAY_PATH = "/__portal__"

# Protocol version — bumped on breaking changes.
PROTOCOL_VERSION = 1


def make_relay_url(relay_host: str, channel: str, side: str) -> str:
    """Build the relay WebSocket URL."""
    scheme = "ws" if relay_host.startswith(("localhost", "127.0.0.1")) else "wss"
    return f"{scheme}://{relay_host}{RELAY_PATH}?v={PROTOCOL_VERSION}&channel={channel}&side={side}"


def chunk_count(file_size: int) -> int:
    """Number of chunks needed to transfer a file."""
    return max(1, math.ceil(file_size / FILE_CHUNK_SIZE))


def make_exec(
    code: str, json_output: bool = False, timeout: int = DEFAULT_EXEC_TIMEOUT
) -> dict:
    return {
        "type": "exec",
        "code": code,
        "json_output": json_output,
        "timeout": timeout,
    }


def make_exec_stdout(data: str) -> dict:
    return {"type": "exec_stdout", "data": data}


def make_exec_result(
    return_value: str | None, error: str | None, stdout: str = ""
) -> dict:
    return {
        "type": "exec_result",
        "stdout": stdout,
        "return_value": return_value,
        "error": error,
    }


def make_error(error: str) -> dict:
    return {"type": "error", "error": error}


def make_file_pull(remote_path: str) -> dict:
    return {"type": "file_pull", "remote_path": remote_path}


def make_file_data(name: str, chunk: int, chunks: int, data: bytes) -> dict:
    return {
        "type": "file_data",
        "name": name,
        "chunk": chunk,
        "chunks": chunks,
        "data": base64.b64encode(data).decode("ascii"),
    }


def make_file_push(remote_path: str, chunk: int, chunks: int, data: bytes) -> dict:
    return {
        "type": "file_push",
        "remote_path": remote_path,
        "chunk": chunk,
        "chunks": chunks,
        "data": base64.b64encode(data).decode("ascii"),
    }


def make_file_push_result(path: str, total_bytes: int) -> dict:
    return {"type": "file_push_result", "path": path, "bytes": total_bytes}


def make_ping() -> dict:
    return {"type": "ping"}


def make_pong() -> dict:
    return {"type": "pong"}
