"""Request bodies arrive intact through every h1 body path.

Drives h1.handle_connection over a socketpair with a real Worker (the
shared server_stubs harness) and a handler that hashes request.body,
then verifies the digest for each ingest shape:

- declared Content-Length body held in memory (<= worker.body_max_memory_size)
- declared Content-Length body spooled to disk (> worker.body_max_memory_size)
- chunked body held in memory
- chunked body spooled to disk
"""

from __future__ import annotations

import asyncio
import hashlib
import random
from typing import Any

from plain.http import Response
from plain.server.workers.worker import Worker
from server_stubs import (
    chunked_payload,
    chunked_request,
    h1_connect,
    h1_roundtrip,
    length_request,
    make_worker,
)


class _DigestHandler:
    """Returns sha256(body) so tests can verify integrity end to end."""

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


def test_in_memory_length_body_integrity():
    body = _pattern(1024 * 1024)
    worker = make_worker(handler=_DigestHandler())
    worker.body_max_memory_size = 4 * 1024 * 1024  # comfortably in memory
    response = asyncio.run(_roundtrip(worker, length_request(body)))
    assert response == _expected(body)


def test_spooled_length_body_integrity():
    body = _pattern(1024 * 1024)
    worker = make_worker(handler=_DigestHandler())
    worker.body_max_memory_size = 64 * 1024  # force the disk spool
    response = asyncio.run(_roundtrip(worker, length_request(body)))
    assert response == _expected(body)


def test_in_memory_chunked_body_integrity():
    body = _pattern(1024 * 1024)
    worker = make_worker(handler=_DigestHandler())
    worker.body_max_memory_size = 4 * 1024 * 1024  # comfortably in memory
    response = asyncio.run(_roundtrip(worker, chunked_request(body, 12345)))
    assert response == _expected(body)


def test_spooled_chunked_body_integrity():
    body = _pattern(1024 * 1024)
    worker = make_worker(handler=_DigestHandler())
    worker.body_max_memory_size = 64 * 1024  # force the disk spool
    response = asyncio.run(_roundtrip(worker, chunked_request(body, 12345)))
    assert response == _expected(body)


class _FramingHandler:
    """Reports the framing headers and ingest stamp the app sees, post-ingest."""

    async def handle(self, request: Any, executor: Any) -> Response:
        cl = request.headers.get("Content-Length")
        te = request.headers.get("Transfer-Encoding")
        ingested = request._body_ingest_seconds is not None
        return Response(
            f"cl={cl} te={te} ingested={ingested}", content_type="text/plain"
        )


def test_chunked_request_is_dechunked_for_the_app():
    # The body is fully received before dispatch, so the app sees a
    # chunked request exactly like a buffering gateway would forward it:
    # a real Content-Length, no Transfer-Encoding. Content-Length
    # consumers (multipart parsing) then work on chunked uploads too.
    body = b"x" * 1000
    worker = make_worker(handler=_FramingHandler())
    response = asyncio.run(_roundtrip(worker, chunked_request(body, 100)))
    assert response == b"cl=1000 te=None ingested=True"


def test_bodyless_request_has_no_ingest_stamp():
    # The ingest observability stamp only appears when a body was
    # actually received — a bodiless request records nothing.
    worker = make_worker(handler=_FramingHandler())
    response = asyncio.run(
        _roundtrip(worker, b"GET / HTTP/1.1\r\nHost: testserver\r\n\r\n")
    )
    assert response == b"cl=None te=None ingested=False"


class _FormFieldHandler:
    """Parses multipart form data and echoes one field."""

    async def handle(self, request: Any, executor: Any) -> Response:
        loop = asyncio.get_running_loop()
        value = await loop.run_in_executor(
            executor, lambda: request.form_data.get("name", "")
        )
        return Response(f"name={value}", content_type="text/plain")


def test_chunked_multipart_form_is_parsed():
    # Multipart parsing keys off Content-Length — before de-chunking,
    # a chunked multipart POST silently parsed to an empty form.
    multipart_body = (
        b"--testboundary\r\n"
        b'Content-Disposition: form-data; name="name"\r\n\r\n'
        b"plain\r\n"
        b"--testboundary--\r\n"
    )
    request = (
        b"POST / HTTP/1.1\r\nHost: testserver\r\n"
        b"Content-Type: multipart/form-data; boundary=testboundary\r\n"
        b"Transfer-Encoding: chunked\r\n\r\n" + chunked_payload(multipart_body, 10)
    )
    worker = make_worker(handler=_FormFieldHandler())
    response = asyncio.run(_roundtrip(worker, request))
    assert response == b"name=plain"


def test_keepalive_survives_stray_crlf_between_requests():
    # RFC 9112 §2.2: a stray CRLF after a POST body — arriving in its
    # own segment, so it reads as the start of the next request — is
    # ignored rather than 400-ing the request behind it.
    async def scenario() -> None:
        body = b"hello"
        worker = make_worker(handler=_DigestHandler())
        client = await h1_connect(worker)
        try:
            await client.send(length_request(body))
            _, response = await client.read_response()
            assert response == _expected(body)
            await client.send(b"\r\n")  # stray CRLF, its own segment
            await asyncio.sleep(0.05)
            await client.send(length_request(body))
            _, response = await client.read_response()
            assert response == _expected(body)
        finally:
            client.teardown()

    asyncio.run(scenario())
