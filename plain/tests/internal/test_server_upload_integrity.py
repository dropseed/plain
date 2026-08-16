"""Request bodies arrive intact through every h1 body path.

Drives h1.handle_connection over a socketpair with a real Worker (the
shared server_stubs harness) and a handler that hashes request.body,
then verifies the digest for each body strategy:

- pre-buffered Content-Length body (<= worker.max_body)
- bridged Content-Length body (> worker.max_body, AsyncBridgeUnreader)
- pre-buffered chunked body
- chunked body that outgrows max_body mid-read (_BodyTooLarge fallback
  to the bridge with partial data)
"""

from __future__ import annotations

import asyncio
import hashlib
import random
from typing import Any

from plain.http import Response
from plain.server.workers.worker import Worker
from server_stubs import chunked_request, h1_roundtrip, length_request, make_worker


class _DigestHandler:
    """Returns sha256(body) so tests can verify integrity end to end.

    Reads the body in the thread pool — bridge bodies block the calling
    thread, so they must not be read on the event loop.
    """

    async def handle(self, request: Any, executor: Any) -> Response:
        loop = asyncio.get_running_loop()
        body = await loop.run_in_executor(executor, lambda: request.body)
        digest = hashlib.sha256(body).hexdigest()
        return Response(f"{len(body)}:{digest}", content_type="text/plain")


async def _roundtrip(worker: Worker, request: bytes) -> bytes:
    """Send one raw request, return the response body."""
    _, body = await h1_roundtrip(worker, request)
    return body


def _expected(body: bytes) -> bytes:
    return f"{len(body)}:{hashlib.sha256(body).hexdigest()}".encode()


def _pattern(n: int) -> bytes:
    return random.Random(7).randbytes(n)


def test_prebuffered_length_body_integrity():
    body = _pattern(1024 * 1024)
    worker = make_worker(handler=_DigestHandler())
    assert len(body) <= worker.max_body  # pre-buffer path
    response = asyncio.run(_roundtrip(worker, length_request(body)))
    assert response == _expected(body)


def test_bridged_length_body_integrity():
    body = _pattern(1024 * 1024)
    worker = make_worker(handler=_DigestHandler())
    worker.max_body = 64 * 1024  # force the bridge path
    response = asyncio.run(_roundtrip(worker, length_request(body)))
    assert response == _expected(body)


def test_prebuffered_chunked_body_integrity():
    body = _pattern(1024 * 1024)
    worker = make_worker(handler=_DigestHandler())
    assert len(body) <= worker.max_body  # pre-buffers, chunked
    response = asyncio.run(_roundtrip(worker, chunked_request(body, 12345)))
    assert response == _expected(body)


def test_chunked_body_falls_back_to_bridge_with_integrity():
    body = _pattern(1024 * 1024)
    worker = make_worker(handler=_DigestHandler())
    # Chunked pre-buffering overflows max_body mid-read and falls back to
    # the bridge, handing over the partial data (_BodyTooLarge path).
    worker.max_body = 64 * 1024
    response = asyncio.run(_roundtrip(worker, chunked_request(body, 12345)))
    assert response == _expected(body)
