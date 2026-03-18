"""Message protocol for portal communication.

Messages are JSON dicts encrypted with NaCl before being sent through
the relay. The relay only sees opaque bytes.

Message types:
  exec           - Execute Python code (local → remote)
  exec_result    - Execution result (remote → local)
  file_pull      - Request a file (local → remote)
  file_data      - File contents chunk (remote → local)
  file_push      - Send a file chunk (local → remote)
  file_push_result - File push confirmation (remote → local)
  ping           - Keepalive (either direction)
  pong           - Keepalive response (either direction)
"""

from __future__ import annotations

import base64

# Max chunk size for file transfers (256KB).
# Keeps individual WebSocket messages small for the relay.
FILE_CHUNK_SIZE = 256 * 1024

# Max file size for transfers (50MB).
MAX_FILE_SIZE = 50 * 1024 * 1024

# Relay WebSocket endpoint.
DEFAULT_RELAY_HOST = "portal.plainframework.com"
RELAY_PATH = "/__portal__"

# Protocol version — bumped on breaking changes.
PROTOCOL_VERSION = 1


def make_exec(code: str, json_output: bool = False) -> dict:
    return {"type": "exec", "code": code, "json_output": json_output}


def make_exec_result(stdout: str, return_value: str | None, error: str | None) -> dict:
    return {
        "type": "exec_result",
        "stdout": stdout,
        "return_value": return_value,
        "error": error,
    }


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
