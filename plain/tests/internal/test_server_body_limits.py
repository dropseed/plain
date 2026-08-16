"""SERVER_MAX_REQUEST_BODY_SIZE is enforced with 413s on h1 and h2.

The policy cap is independent of buffering strategy (SERVER_BODY_PREBUFFER_SIZE):

- h1 declared Content-Length over the cap: rejected from the headers,
  before the body is transferred — and before any 100 Continue.
- h1 chunked (undeclared length) over the cap: the CappedBodyStream
  backstop raises ContentTooLargeError413 as the app reads.
- h2 declared content-length over the cap: stream rejected at the
  headers with a 413 response.
- h2 stream exceeding the cap mid-data: 413.
"""

from __future__ import annotations

import asyncio

import pytest
from plain.http import ContentTooLargeError413, Response
from plain.runtime import settings
from plain.server.http.body import Body, LengthReader
from plain.server.http.request import CappedBodyStream
from plain.server.http.unreader import BufferUnreader
from server_stubs import (
    BodyLengthHandler,
    chunked_request,
    h1_connect,
    h1_roundtrip,
    h2_connect,
    length_request,
    make_worker,
)

# ---------------------------------------------------------------------------
# CappedBodyStream
# ---------------------------------------------------------------------------


def _capped_stream(data: bytes, cap: int) -> CappedBodyStream:
    return CappedBodyStream(Body(LengthReader(BufferUnreader(data), len(data))), cap)


def test_capped_stream_passes_bodies_within_cap():
    stream = _capped_stream(b"x" * 100, 100)
    assert stream.read() == b"x" * 100


def test_capped_stream_raises_past_cap():
    stream = _capped_stream(b"x" * 101, 100)
    with pytest.raises(ContentTooLargeError413):
        stream.read()


def test_capped_stream_counts_across_reads():
    stream = _capped_stream(b"x" * 150, 100)
    stream.read(60)
    with pytest.raises(ContentTooLargeError413):
        stream.read(60)


def test_capped_stream_negative_size_reads_are_memory_bounded():
    # read(-1)/readline(-1) are the standard file-like read-to-EOF idiom
    # and must take the same bounded path as read(None) — passing the -1
    # through would materialize the whole body before the count raises.
    requested: list[int | None] = []

    class SpyBody(Body):
        def read(self, size: int | None = None) -> bytes:
            requested.append(size)
            return super().read(size)

        def readline(self, size: int | None = None) -> bytes:
            requested.append(size)
            return super().readline(size)

    n = 100_000

    def fresh_stream() -> CappedBodyStream:
        return CappedBodyStream(
            SpyBody(LengthReader(BufferUnreader(b"x" * n), n)), 1000
        )

    with pytest.raises(ContentTooLargeError413):
        fresh_stream().read(-1)
    with pytest.raises(ContentTooLargeError413):
        fresh_stream().readline(-1)
    assert all(size is not None and 0 < size <= 1001 for size in requested)


def test_capped_stream_unsized_read_is_memory_bounded():
    # An unsized read() must pull from the underlying stream in
    # allowance-bounded pieces — draining it in one call would
    # materialize an over-cap body in full before the count raises.
    requested: list[int | None] = []

    class SpyBody(Body):
        def read(self, size: int | None = None) -> bytes:
            requested.append(size)
            return super().read(size)

    n = 100_000
    body = SpyBody(LengthReader(BufferUnreader(b"x" * n), n))
    stream = CappedBodyStream(body, 1000)
    with pytest.raises(ContentTooLargeError413):
        stream.read()
    assert all(size is not None and size <= 1001 for size in requested)


# ---------------------------------------------------------------------------
# Worker settings wiring
# ---------------------------------------------------------------------------


def test_worker_derives_thresholds_from_server_settings():
    worker = make_worker()
    assert worker.max_request_body == settings.SERVER_MAX_REQUEST_BODY_SIZE
    assert worker.max_body == min(
        settings.SERVER_BODY_PREBUFFER_SIZE, settings.SERVER_MAX_REQUEST_BODY_SIZE
    )


def test_worker_prebuffer_never_exceeds_policy_cap(monkeypatch):
    monkeypatch.setattr(settings, "SERVER_MAX_REQUEST_BODY_SIZE", 1024)
    worker = make_worker()
    assert worker.max_body == 1024
    # The h2 buffering budget derives from the CONFIGURED prebuffer, not
    # the policy-clamped one — a small request cap must not shrink the
    # concurrency budget for many small legal streams.
    assert worker.max_h2_aggregate_body == settings.SERVER_BODY_PREBUFFER_SIZE * 10


def test_worker_unlimited_cap_keeps_h2_memory_floor(monkeypatch):
    # h2 buffers bodies fully in RAM, so even an unlimited policy cap
    # must leave the per-connection buffering budget bounded.
    monkeypatch.setattr(settings, "SERVER_MAX_REQUEST_BODY_SIZE", None)
    worker = make_worker()
    assert worker.max_request_body is None
    assert worker.max_h2_aggregate_body == settings.SERVER_BODY_PREBUFFER_SIZE * 10


def test_worker_rejects_negative_cap(monkeypatch):
    from plain.exceptions import ImproperlyConfigured

    monkeypatch.setattr(settings, "SERVER_MAX_REQUEST_BODY_SIZE", -1)
    with pytest.raises(ImproperlyConfigured):
        make_worker()


# ---------------------------------------------------------------------------
# h1 (socketpair through handle_connection)
# ---------------------------------------------------------------------------


def test_h1_declared_content_length_over_cap_is_rejected_early():
    async def scenario() -> None:
        worker = make_worker(handler=BodyLengthHandler())
        worker.max_request_body = 1000
        # Declared over-cap body, none of it sent: the 413 must come back
        # from the headers alone.
        request = b"POST / HTTP/1.1\r\nHost: testserver\r\nContent-Length: 2000\r\n\r\n"
        headers, _ = await h1_roundtrip(worker, request)
        assert headers.split(b"\r\n", 1)[0] == b"HTTP/1.1 413 Content Too Large"

    asyncio.run(scenario())


def test_h1_oversized_expect_continue_is_refused_without_100():
    async def scenario() -> None:
        worker = make_worker(handler=BodyLengthHandler())
        worker.max_request_body = 1000
        request = (
            b"POST / HTTP/1.1\r\nHost: testserver\r\n"
            b"Expect: 100-continue\r\nContent-Length: 2000\r\n\r\n"
        )
        headers, _ = await h1_roundtrip(worker, request)
        # The first (and only) response is the 413 — the client was
        # never told to start sending the body.
        assert b"413" in headers.split(b"\r\n", 1)[0]
        assert b"100 Continue" not in headers

    asyncio.run(scenario())


def test_h1_content_length_within_cap_is_served():
    async def scenario() -> None:
        worker = make_worker(handler=BodyLengthHandler())
        worker.max_request_body = 1000
        headers, body = await h1_roundtrip(worker, length_request(b"x" * 500))
        assert b"200" in headers.split(b"\r\n", 1)[0]
        assert body == b"500"

    asyncio.run(scenario())


def test_h1_chunked_body_over_cap_is_rejected_at_read_time():
    async def scenario() -> None:
        worker = make_worker(handler=BodyLengthHandler())
        # Cap above the prebuffer threshold so the body streams via the
        # bridge — the only path the CappedBodyStream backstop serves.
        worker.max_body = 1024
        worker.max_request_body = 4096
        headers, body = await h1_roundtrip(worker, chunked_request(b"x" * 10_000, 1000))
        assert b"413" in headers.split(b"\r\n", 1)[0]
        assert body == b"too large"

    asyncio.run(scenario())


def test_h1_prebuffered_chunked_overshoot_is_rejected():
    # The chunked pre-buffer detects completion before the size check, so
    # a body can arrive fully at up to max_body + one recv — over the
    # policy cap when cap <= prebuffer. It must still be 413'd before
    # dispatch, not served.
    async def scenario() -> None:
        worker = make_worker(handler=BodyLengthHandler())
        worker.max_body = 20_000
        worker.max_request_body = 20_000
        headers, _ = await h1_roundtrip(worker, chunked_request(b"x" * 21_000, 1000))
        assert b"413" in headers.split(b"\r\n", 1)[0]

    asyncio.run(scenario())


def test_h1_successful_chunked_bridge_request_closes_promptly():
    # A fully-consumed chunked bridge body must not linger — the client
    # has its response and no reason to close first, so an unconditional
    # linger would pin the connection slot for the full timeout on every
    # successful request (measured at 2s before the fix).
    async def scenario() -> None:
        worker = make_worker(handler=BodyLengthHandler())
        worker.max_body = 1024
        worker.max_request_body = 100_000
        client = await h1_connect(worker)
        try:
            await client.send(chunked_request(b"x" * 10_000, 1000))
            _headers, body = await client.read_response()
            assert body == b"10000"
            # The connection loop must exit without waiting out a linger.
            await asyncio.wait_for(client.server_task, timeout=1.0)
        finally:
            client.teardown()

    asyncio.run(scenario())


def test_h1_chunked_body_unread_by_app_is_served():
    # h1 dispatches while a chunked body is still inbound, so a view that
    # never reads the body can complete before the cap is ever consulted
    # — the request succeeds and the connection closes (the cap bounds
    # what the app READS on h1; h2 enforces at ingest instead, because it
    # buffers the whole body before dispatch). Pinned so a change here is
    # a deliberate decision, not an accident.
    class NoReadHandler:
        async def handle(self, request, executor):
            return Response(b"ignored body", content_type="text/plain")

    async def scenario() -> None:
        worker = make_worker(handler=NoReadHandler())
        worker.max_body = 1024
        worker.max_request_body = 4096
        headers, body = await h1_roundtrip(worker, chunked_request(b"x" * 10_000, 1000))
        assert b"200" in headers.split(b"\r\n", 1)[0]
        assert body == b"ignored body"

    asyncio.run(scenario())


def test_h1_chunked_body_within_cap_is_served():
    async def scenario() -> None:
        worker = make_worker(handler=BodyLengthHandler())
        worker.max_body = 1024
        worker.max_request_body = 100_000
        headers, body = await h1_roundtrip(worker, chunked_request(b"x" * 10_000, 1000))
        assert b"200" in headers.split(b"\r\n", 1)[0]
        assert body == b"10000"

    asyncio.run(scenario())


# ---------------------------------------------------------------------------
# h2 (socketpair through async_handle_h2_connection)
# ---------------------------------------------------------------------------


async def _h2_post_status(
    *,
    content_length: int | None,
    body_frames: list[bytes],
    max_request_body: int | None,
    max_aggregate_body: int | None = None,
) -> str:
    """POST through a real h2 client; return the :status received."""
    client, server_task, executor = await h2_connect(
        BodyLengthHandler(),
        asyncio.Event(),
        max_request_body=max_request_body,
        max_aggregate_body=max_aggregate_body,
    )
    try:
        await client.request(1, body_frames=body_frames, content_length=content_length)
        return await client.response_status(1)
    finally:
        server_task.cancel()
        client.writer.close()
        executor.shutdown(wait=False)


def test_h2_declared_content_length_over_cap_rejected_at_headers():
    status = asyncio.run(
        _h2_post_status(
            content_length=2000, body_frames=[b"x" * 2000], max_request_body=1000
        )
    )
    assert status == "413"


def test_h2_stream_exceeding_cap_mid_data_rejected():
    # No declared length; frames push past the cap.
    status = asyncio.run(
        _h2_post_status(
            content_length=None,
            body_frames=[b"x" * 800, b"x" * 800],
            max_request_body=1000,
        )
    )
    assert status == "413"


def test_h2_body_within_cap_is_served():
    status = asyncio.run(
        _h2_post_status(
            content_length=500, body_frames=[b"x" * 500], max_request_body=10_000
        )
    )
    assert status == "200"


def test_h2_unlimited_policy_still_bounds_streams_at_buffer_floor():
    # With no policy cap, the buffering budget still bounds h2 bodies —
    # h2 has no streaming path, so this is the memory floor. The
    # oversized stream itself gets a 413 (per-stream floor, checked
    # first), not a retry-inviting 503.
    status = asyncio.run(
        _h2_post_status(
            content_length=None,
            body_frames=[b"x" * 800, b"x" * 800],
            max_request_body=None,
            max_aggregate_body=1000,
        )
    )
    assert status == "413"
