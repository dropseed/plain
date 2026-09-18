"""SERVER_MAX_REQUEST_BODY_SIZE is enforced with 413s on h1 and h2.

The policy cap is independent of buffering strategy (SERVER_BODY_MAX_MEMORY_SIZE):

- h1 declared Content-Length over the cap: rejected from the headers,
  before the body is transferred — and before any 100 Continue.
- h1 chunked (undeclared length) over the cap: the BodySink enforces the
  cap on received bytes at ingest, before dispatch — even when the view
  would never read the body.
- h2 declared content-length over the cap: stream rejected at the
  headers with a 413 response.
- h2 stream exceeding the cap mid-data: 413.
"""

from __future__ import annotations

import asyncio

import h2.errors
import pytest
from plain.http import Response
from plain.runtime import settings
from plain.server.http.sink import BodyBudget
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
# Worker settings wiring
# ---------------------------------------------------------------------------


def test_worker_derives_thresholds_from_server_settings():
    worker = make_worker()
    assert worker.max_request_body == settings.SERVER_MAX_REQUEST_BODY_SIZE
    assert worker.body_max_memory_size == min(
        settings.SERVER_BODY_MAX_MEMORY_SIZE, settings.SERVER_MAX_REQUEST_BODY_SIZE
    )


def test_worker_prebuffer_never_exceeds_policy_cap(monkeypatch):
    monkeypatch.setattr(settings, "SERVER_MAX_REQUEST_BODY_SIZE", 1024)
    worker = make_worker()
    assert worker.body_max_memory_size == 1024


def test_worker_wires_the_inflight_body_budget():
    worker = make_worker()
    assert worker.body_budget.limit == settings.SERVER_MAX_INFLIGHT_BODY_SIZE
    assert worker.body_budget.used == 0


def test_worker_rejects_negative_cap(monkeypatch):
    from plain.exceptions import ImproperlyConfigured

    monkeypatch.setattr(settings, "SERVER_MAX_REQUEST_BODY_SIZE", -1)
    with pytest.raises(ImproperlyConfigured):
        make_worker()


def test_worker_rejects_negative_inflight_budget(monkeypatch):
    from plain.exceptions import ImproperlyConfigured

    monkeypatch.setattr(settings, "SERVER_MAX_INFLIGHT_BODY_SIZE", -1)
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


def test_h1_chunked_body_over_cap_is_rejected_at_ingest():
    # Chunked bodies declare no length, so the cap binds on received
    # bytes inside the sink — before dispatch.
    async def scenario() -> None:
        worker = make_worker(handler=BodyLengthHandler())
        worker.body_max_memory_size = 1024
        worker.max_request_body = 4096
        headers, _ = await h1_roundtrip(worker, chunked_request(b"x" * 10_000, 1000))
        assert b"413" in headers.split(b"\r\n", 1)[0]

    asyncio.run(scenario())


def test_h1_chunked_body_over_cap_rejected_even_when_app_never_reads():
    # Ingest-time enforcement means a view that ignores the body can't
    # accidentally accept an over-cap upload. (Before the body sink,
    # this request was SERVED — the read-time backstop never fired for
    # an unread body. Deliberate semantic flip.)
    class NoReadHandler:
        async def handle(self, request, executor):
            return Response(b"ignored body", content_type="text/plain")

    async def scenario() -> None:
        worker = make_worker(handler=NoReadHandler())
        worker.body_max_memory_size = 1024
        worker.max_request_body = 4096
        headers, _ = await h1_roundtrip(worker, chunked_request(b"x" * 10_000, 1000))
        assert b"413" in headers.split(b"\r\n", 1)[0]

    asyncio.run(scenario())


def test_h1_chunked_body_exactly_at_cap_is_served():
    async def scenario() -> None:
        worker = make_worker(handler=BodyLengthHandler())
        worker.body_max_memory_size = 1024
        worker.max_request_body = 20_000
        headers, body = await h1_roundtrip(worker, chunked_request(b"x" * 20_000, 1000))
        assert b"200" in headers.split(b"\r\n", 1)[0]
        assert body == b"20000"

    asyncio.run(scenario())


def test_h1_chunked_body_within_cap_is_served():
    async def scenario() -> None:
        worker = make_worker(handler=BodyLengthHandler())
        worker.body_max_memory_size = 1024
        worker.max_request_body = 100_000
        headers, body = await h1_roundtrip(worker, chunked_request(b"x" * 10_000, 1000))
        assert b"200" in headers.split(b"\r\n", 1)[0]
        assert body == b"10000"

    asyncio.run(scenario())


def test_h1_spooled_body_keeps_the_connection_alive():
    # A body past the spool threshold is fully consumed off the wire at
    # ingest, so the connection is safely reusable — the sink's headline
    # improvement over the old lazy-streaming path, which had to force
    # Connection: close. (Deliberate semantic flip.)
    async def scenario() -> None:
        worker = make_worker(handler=BodyLengthHandler())
        worker.body_max_memory_size = 1024
        worker.max_request_body = 100_000
        client = await h1_connect(worker)
        try:
            await client.send(length_request(b"x" * 10_000))
            headers, body = await client.read_response()
            assert b"200" in headers.split(b"\r\n", 1)[0]
            assert body == b"10000"
            assert b"connection: close" not in headers.lower()
            # The connection serves a second request.
            await client.send(length_request(b"y" * 500))
            headers2, body2 = await client.read_response()
            assert b"200" in headers2.split(b"\r\n", 1)[0]
            assert body2 == b"500"
        finally:
            client.teardown()

    asyncio.run(scenario())


def test_h1_bad_trailer_name_is_400_not_dropped():
    # A malformed trailer header name raises InvalidHeaderName (a sibling
    # of InvalidHeader) during ingest — it must map to a 400, not escape
    # the handler and drop the connection with no response.
    async def scenario() -> None:
        worker = make_worker(handler=BodyLengthHandler())
        request = (
            b"POST / HTTP/1.1\r\nHost: testserver\r\n"
            b"Transfer-Encoding: chunked\r\n\r\n"
            b"5\r\nHELLO\r\n0\r\nBad Name: x\r\n\r\n"
        )
        headers, _ = await h1_roundtrip(worker, request)
        assert headers.split(b"\r\n", 1)[0] == b"HTTP/1.1 400 Bad Request"

    asyncio.run(scenario())


def test_h1_non_hex_chunk_size_is_400():
    # int(_, 16) would accept "0x5"/"1_0"; the strict hex check 400s them.
    async def scenario() -> None:
        worker = make_worker(handler=BodyLengthHandler())
        request = (
            b"POST / HTTP/1.1\r\nHost: testserver\r\n"
            b"Transfer-Encoding: chunked\r\n\r\n"
            b"1_0\r\n" + b"x" * 16 + b"\r\n0\r\n\r\n"
        )
        headers, _ = await h1_roundtrip(worker, request)
        assert headers.split(b"\r\n", 1)[0] == b"HTTP/1.1 400 Bad Request"

    asyncio.run(scenario())


def test_h1_body_tolerates_multi_second_stall():
    # A large upload with an inter-packet stall longer than the header
    # progress timeout (2s) must still succeed — the body phase gets a
    # generous per-recv budget, with the throughput floor (not this
    # timeout) guarding against slow-drip.
    async def scenario() -> None:
        worker = make_worker(handler=BodyLengthHandler())
        client = await h1_connect(worker)
        try:
            await client.send(
                b"POST / HTTP/1.1\r\nHost: testserver\r\nContent-Length: 10\r\n\r\n"
            )
            await client.send(b"hello")
            await asyncio.sleep(2.5)  # past RECV_PROGRESS_TIMEOUT
            await client.send(b"world")
            headers, body = await client.read_response()
            assert b"200" in headers.split(b"\r\n", 1)[0]
            assert body == b"10"
        finally:
            client.teardown()

    asyncio.run(scenario())


def test_h1_trailing_crlf_after_body_keeps_connection_alive():
    # A stray CRLF after a declared-length body is RFC 9112 tolerance,
    # not a pipelined request — the connection must stay reusable.
    async def scenario() -> None:
        worker = make_worker(handler=BodyLengthHandler())
        client = await h1_connect(worker)
        try:
            await client.send(
                b"POST / HTTP/1.1\r\nHost: testserver\r\n"
                b"Content-Length: 5\r\n\r\nHELLO\r\n"
            )
            headers, _ = await client.read_response()
            assert b"200" in headers.split(b"\r\n", 1)[0]
            assert b"connection: close" not in headers.lower()
            await client.send(length_request(b"y" * 3))
            headers2, body2 = await client.read_response()
            assert b"200" in headers2.split(b"\r\n", 1)[0]
            assert body2 == b"3"
        finally:
            client.teardown()

    asyncio.run(scenario())


def test_h1_chunked_request_closes_promptly_after_response():
    # A fully-consumed chunked body must not linger the connection —
    # the request is done, nothing is inbound.
    async def scenario() -> None:
        worker = make_worker(handler=BodyLengthHandler())
        worker.body_max_memory_size = 1024
        worker.max_request_body = 100_000
        client = await h1_connect(worker)
        try:
            request = chunked_request(b"x" * 10_000, 1000)
            await client.send(request[:-1])
            await client.send(request[-1:])
            _headers, body = await client.read_response()
            assert body == b"10000"
            # Close the client side; the server loop must exit promptly
            # rather than waiting out any linger window.
            client.writer.close()
            await asyncio.wait_for(client.server_task, timeout=1.0)
        finally:
            client.teardown()

    asyncio.run(scenario())


# ---------------------------------------------------------------------------
# h2 (socketpair through async_handle_h2_connection)
# ---------------------------------------------------------------------------


async def _h2_post_status(
    *,
    content_length: int | None,
    body_frames: list[bytes],
    max_request_body: int | None,
    max_inflight_body: int | None = None,
    spool_size: int | None = None,
) -> str:
    """POST through a real h2 client; return the :status received."""
    client, server_task, executor = await h2_connect(
        BodyLengthHandler(),
        asyncio.Event(),
        max_request_body=max_request_body,
        max_inflight_body=max_inflight_body,
        spool_size=spool_size,
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


def test_h2_body_over_spool_threshold_is_served_from_disk():
    # A body past the sink's spool threshold spills to the anonymous
    # temp file and must round-trip through it unchanged.
    status = asyncio.run(
        _h2_post_status(
            content_length=8000,
            body_frames=[b"x" * 4000, b"x" * 4000],
            max_request_body=100_000,
            spool_size=1024,
        )
    )
    assert status == "200"


def test_h2_unlimited_policy_still_bounds_streams_at_budget_floor():
    # With no policy cap, the in-flight budget still bounds h2 bodies —
    # the oversized stream itself gets a 413 (per-stream floor, checked
    # first), not a retry-inviting 503.
    status = asyncio.run(
        _h2_post_status(
            content_length=None,
            body_frames=[b"x" * 800, b"x" * 800],
            max_request_body=None,
            max_inflight_body=1000,
        )
    )
    assert status == "413"


def test_h2_inflight_budget_exhaustion_is_503():
    # A second stream arriving while the budget is held by the first
    # gets the load-shedding 503, not a 413 — its own body is legal.
    async def scenario() -> str:
        client, server_task, executor = await h2_connect(
            BodyLengthHandler(),
            asyncio.Event(),
            max_request_body=500,
            max_inflight_body=600,
        )
        try:
            # Stream 1: 400 bytes held in flight (no END_STREAM yet).
            await client.request(
                1, body_frames=[b"x" * 400], content_length=None, end_stream=False
            )
            # Stream 3: 400 more would exceed the 600-byte budget.
            await client.request(3, body_frames=[b"x" * 400], content_length=None)
            return await client.response_status(3)
        finally:
            server_task.cancel()
            client.writer.close()
            executor.shutdown(wait=False)

    assert asyncio.run(scenario()) == "503"


def test_h2_complete_declared_body_not_swept_by_rate_floor():
    # A stream that delivered its full declared body but hasn't sent
    # END_STREAM (waiting on trailers, say) must not be 408'd — it's
    # done, not dripping. Uses the drip grace shrink from the rate test
    # module scope; here we assert a healthy complete body is served.
    async def scenario() -> str:
        client, server_task, executor = await h2_connect(
            BodyLengthHandler(),
            asyncio.Event(),
            max_request_body=100_000,
            body_min_rate=100_000,
        )
        try:
            # Full 10-byte body, then END_STREAM promptly — the common
            # complete-body case must return 200 under an aggressive floor.
            await client.request(1, body_frames=[b"x" * 10], content_length=10)
            return await client.response_status(1)
        finally:
            server_task.cancel()
            client.writer.close()
            executor.shutdown(wait=False)

    assert asyncio.run(scenario()) == "200"


def test_h2_stream_aborted_in_same_batch_releases_budget():
    # END_STREAM and RST_STREAM arriving in one frame batch cancel the
    # dispatch task before its coroutine ever runs — not even its
    # except/finally execute — so the sink release lives in the task's
    # done callback. Without that, each aborted upload's bytes stay
    # charged to the worker-wide budget forever, until enough aborts
    # exhaust it and the whole worker 503s until recycled.
    async def scenario() -> None:
        budget = BodyBudget(100_000)
        client, server_task, executor = await h2_connect(
            BodyLengthHandler(),
            asyncio.Event(),
            max_request_body=50_000,
            body_budget=budget,
        )
        try:
            for stream_id in (1, 3, 5):
                # Queue HEADERS + DATA(END_STREAM) + RST_STREAM locally,
                # then flush once so the server sees a single batch.
                client.conn.send_headers(
                    stream_id,
                    [
                        (":method", "POST"),
                        (":path", "/"),
                        (":scheme", "http"),
                        (":authority", "testserver"),
                    ],
                )
                client.conn.send_data(stream_id, b"x" * 4000, end_stream=True)
                client.conn.reset_stream(
                    stream_id, error_code=h2.errors.ErrorCodes.CANCEL
                )
                await client.flush()

            # The connection still serves, and every aborted body's
            # charge comes back once its done callback has run.
            await client.request(7, body_frames=[b"x" * 100], content_length=100)
            assert await client.response_status(7) == "200"
            for _ in range(100):
                if budget.used == 0:
                    break
                await asyncio.sleep(0.01)
            assert budget.used == 0
        finally:
            server_task.cancel()
            client.writer.close()
            executor.shutdown(wait=False)

    asyncio.run(scenario())


def test_h1_expect_list_still_gets_100_continue():
    # Expect is a comma-separated list (RFC 9110 §10.1.1) — 100-continue
    # among other members still draws the interim response; a waiting
    # client would otherwise sit in silence until the body recv timeout.
    async def scenario() -> None:
        worker = make_worker(handler=BodyLengthHandler())
        client = await h1_connect(worker)
        try:
            await client.send(
                b"POST / HTTP/1.1\r\nHost: testserver\r\n"
                b"Expect: 100-continue, extension\r\nContent-Length: 5\r\n\r\n"
            )
            interim, _ = await client.read_response()
            assert b"100 Continue" in interim
            await client.send(b"hello")
            headers, body = await client.read_response()
            assert b"200" in headers.split(b"\r\n", 1)[0]
            assert body == b"5"
        finally:
            client.teardown()

    asyncio.run(scenario())


def test_h1_inflight_budget_exhaustion_is_503():
    async def scenario() -> None:
        worker = make_worker(handler=BodyLengthHandler())
        worker.max_request_body = 100_000
        worker.body_budget.limit = 500
        headers, _ = await h1_roundtrip(worker, length_request(b"x" * 2000))
        assert b"503" in headers.split(b"\r\n", 1)[0]
        # Load shedding invites a retry.
        assert b"Retry-After: 1" in headers

    asyncio.run(scenario())


def test_budget_is_released_when_requests_complete():
    async def scenario() -> None:
        worker = make_worker(handler=BodyLengthHandler())
        worker.body_budget.limit = 5000
        client = await h1_connect(worker)
        try:
            for _ in range(3):
                # Each body alone fits the budget; sequential requests
                # only pass if completed bodies release their charge.
                await client.send(length_request(b"x" * 4000))
                headers, body = await client.read_response()
                assert b"200" in headers.split(b"\r\n", 1)[0]
                assert body == b"4000"
            assert worker.body_budget.used == 0
        finally:
            client.teardown()

    asyncio.run(scenario())
