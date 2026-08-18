"""SERVER_BODY_MIN_BYTES_PER_SECOND kills slow-drip request bodies.

Per-recv inactivity timeouts can't stop a client that sends one byte per
interval (R.U.D.Y.) — it stays "active" forever while pinning a
connection and holding in-flight body budget. The throughput floor
counts time spent actively waiting for body bytes and 408s clients that
stay under the rate once the grace period passes.
"""

from __future__ import annotations

import asyncio

import pytest
from plain.http import Response
from plain.server.http import sink
from plain.server.http.sink import BodyRateFloor
from server_stubs import BodyLengthHandler, h1_connect, h2_connect, make_worker

# ---------------------------------------------------------------------------
# BodyRateFloor
# ---------------------------------------------------------------------------


def test_floor_disabled_at_zero_rate():
    rate = BodyRateFloor(0)
    rate.record(waited=100.0, received=0)
    assert not rate.violated()


def test_floor_not_enforced_within_grace(monkeypatch):
    monkeypatch.setattr(sink, "BODY_RATE_GRACE_PERIOD", 5.0)
    rate = BodyRateFloor(240)
    rate.record(waited=4.0, received=0)
    assert not rate.violated()


def test_floor_violated_after_grace(monkeypatch):
    monkeypatch.setattr(sink, "BODY_RATE_GRACE_PERIOD", 5.0)
    rate = BodyRateFloor(240)
    # 1s of post-grace wait needs 240 bytes; only 100 arrived.
    rate.record(waited=6.0, received=100)
    assert rate.violated()


def test_floor_satisfied_by_healthy_rate(monkeypatch):
    monkeypatch.setattr(sink, "BODY_RATE_GRACE_PERIOD", 5.0)
    rate = BodyRateFloor(240)
    # 5s post-grace needs 1200 bytes; sustained rate delivers far more.
    rate.record(waited=10.0, received=240 * 10)
    assert not rate.violated()


def test_floor_does_not_penalize_complete_body_after_a_stall(monkeypatch):
    # A small body delivered in full just after a stall past the grace
    # window must NOT be flagged — the predicate charges only post-grace
    # time, not a cumulative average over the whole wait.
    monkeypatch.setattr(sink, "BODY_RATE_GRACE_PERIOD", 5.0)
    rate = BodyRateFloor(240)
    rate.record(waited=5.5, received=1000)  # 1000B needs 240*0.5=120
    assert not rate.violated()


def test_floor_resets_after_a_met_window(monkeypatch):
    # Early bytes buy at most one window of credit: a fast start
    # followed by silence violates in the next window, instead of
    # banking received/min_rate seconds of allowed dripping (10MB up
    # front must not fund ~12 hours of one-byte drips).
    monkeypatch.setattr(sink, "BODY_RATE_GRACE_PERIOD", 5.0)
    monkeypatch.setattr(sink, "BODY_RATE_WINDOW", 30.0)
    rate = BodyRateFloor(240)
    rate.record(waited=1.0, received=10_000_000)  # fast-start burst
    rate.record(waited=29.0, received=0)
    assert not rate.violated()  # window met by the burst — counters reset
    rate.record(waited=6.0, received=100)  # fresh window, post-grace
    assert rate.violated()


# ---------------------------------------------------------------------------
# h1 end-to-end (socketpair through handle_connection)
# ---------------------------------------------------------------------------


def _drip_grace(monkeypatch) -> None:
    # Shrink the grace period so a drip trips the floor in test time.
    monkeypatch.setattr(sink, "BODY_RATE_GRACE_PERIOD", 0.05)


def test_h1_slow_drip_declared_body_is_408(monkeypatch):
    _drip_grace(monkeypatch)

    async def scenario() -> None:
        worker = make_worker(handler=BodyLengthHandler())
        worker.body_min_rate = 100_000
        client = await h1_connect(worker)
        try:
            await client.send(
                b"POST / HTTP/1.1\r\nHost: testserver\r\nContent-Length: 100000\r\n\r\n"
            )
            await client.send(b"x")
            await asyncio.sleep(0.15)
            await client.send(b"x")
            headers, _ = await client.read_response()
            assert headers.split(b"\r\n", 1)[0] == b"HTTP/1.1 408 Request Timeout"
        finally:
            client.teardown()

    asyncio.run(scenario())


def test_h1_slow_drip_chunked_body_is_408(monkeypatch):
    _drip_grace(monkeypatch)

    async def scenario() -> None:
        worker = make_worker(handler=BodyLengthHandler())
        worker.body_min_rate = 100_000
        client = await h1_connect(worker)
        try:
            await client.send(
                b"POST / HTTP/1.1\r\nHost: testserver\r\n"
                b"Transfer-Encoding: chunked\r\n\r\n"
            )
            await client.send(b"5\r\nabc")
            await asyncio.sleep(0.15)
            await client.send(b"de")
            headers, _ = await client.read_response()
            assert headers.split(b"\r\n", 1)[0] == b"HTTP/1.1 408 Request Timeout"
        finally:
            client.teardown()

    asyncio.run(scenario())


def test_h1_slow_drip_spooled_body_is_408(monkeypatch):
    # The floor applies identically once the body has crossed into the
    # disk spool.
    _drip_grace(monkeypatch)

    async def scenario() -> None:
        worker = make_worker(handler=BodyLengthHandler())
        worker.body_min_rate = 100_000
        worker.body_max_memory_size = 1024  # force the disk spool
        worker.max_request_body = 10_000_000
        client = await h1_connect(worker)
        try:
            await client.send(
                b"POST / HTTP/1.1\r\nHost: testserver\r\nContent-Length: 100000\r\n\r\n"
            )
            await client.send(b"x" * 2048)
            await asyncio.sleep(0.15)
            await client.send(b"x")
            headers, _ = await client.read_response()
            assert headers.split(b"\r\n", 1)[0] == b"HTTP/1.1 408 Request Timeout"
        finally:
            client.teardown()

    asyncio.run(scenario())


def test_h2_slow_drip_stream_is_408(monkeypatch):
    # h2 ingests bodies independently of the app, so wall time since the
    # stream opened is receive time — a stream dripping under the floor
    # is swept on the next frame batch and 408'd, releasing its budget.
    _drip_grace(monkeypatch)

    async def scenario() -> str:
        client, server_task, executor = await h2_connect(
            BodyLengthHandler(),
            asyncio.Event(),
            max_request_body=100_000,
            body_min_rate=100_000,
        )
        try:
            await client.request(
                1, body_frames=[b"x" * 10], content_length=None, end_stream=False
            )
            await asyncio.sleep(0.15)
            # Any frame triggers the sweep; a PING keeps the stream silent.
            client.conn.ping(b"12345678")
            await client.flush()
            return await client.response_status(1)
        finally:
            server_task.cancel()
            client.writer.close()
            executor.shutdown(wait=False)

    assert asyncio.run(scenario()) == "408"


def test_h1_complete_body_served_when_final_bytes_arrive_late(monkeypatch):
    # The floor is consulted only when MORE bytes are needed — the recv
    # that completes the body can never 408 a complete request (client
    # think-time before a small body, a 100-continue producer that
    # computes its payload slowly).
    _drip_grace(monkeypatch)

    async def scenario() -> None:
        worker = make_worker(handler=BodyLengthHandler())
        client = await h1_connect(worker)
        try:
            await client.send(
                b"POST / HTTP/1.1\r\nHost: testserver\r\nContent-Length: 20\r\n\r\n"
            )
            await asyncio.sleep(0.3)  # well past the shrunken grace
            await client.send(b"x" * 20)
            headers, body = await client.read_response()
            assert b"200" in headers.split(b"\r\n", 1)[0]
            assert body == b"20"
        finally:
            client.teardown()

    asyncio.run(scenario())


def test_h1_healthy_upload_unaffected():
    # A normal-speed upload sails through with the floor at its default.
    async def scenario() -> None:
        worker = make_worker(handler=BodyLengthHandler())
        client = await h1_connect(worker)
        try:
            await client.send(
                b"POST / HTTP/1.1\r\nHost: testserver\r\nContent-Length: 5000\r\n\r\n"
                + b"x" * 5000
            )
            headers, body = await client.read_response()
            assert b"200" in headers.split(b"\r\n", 1)[0]
            assert body == b"5000"
        finally:
            client.teardown()

    asyncio.run(scenario())


def test_h2_stalled_upload_swept_while_other_stream_active(monkeypatch):
    # A stalled upload produces no frames of its own, and a long-running
    # response on the same connection keeps the loop from ever going
    # idle — the sweep must run on wait timeouts, not only per frame
    # batch, or the stalled sink holds worker budget for as long as the
    # other stream lives (SSE could hold it indefinitely).
    _drip_grace(monkeypatch)

    class SlowHandler:
        async def handle(self, request, executor):
            await asyncio.sleep(3)
            return Response("done", content_type="text/plain")

    async def scenario() -> str:
        client, server_task, executor = await h2_connect(
            SlowHandler(),
            asyncio.Event(),
            max_request_body=100_000,
            body_min_rate=100_000,
        )
        try:
            await client.request(1)  # dispatched into the slow view
            await client.request(
                3, body_frames=[b"x"], content_length=1000, end_stream=False
            )
            # Total client silence from here on: only a timeout-driven
            # sweep can reach the stalled stream 3.
            return await client.response_status(3, timeout=4.0)
        finally:
            server_task.cancel()
            client.writer.close()
            executor.shutdown(wait=False)

    assert asyncio.run(scenario()) == "408"


def test_worker_rejects_negative_min_rate(monkeypatch):
    from plain.exceptions import ImproperlyConfigured
    from plain.runtime import settings

    monkeypatch.setattr(settings, "SERVER_BODY_MIN_BYTES_PER_SECOND", -1)
    with pytest.raises(ImproperlyConfigured):
        make_worker()
