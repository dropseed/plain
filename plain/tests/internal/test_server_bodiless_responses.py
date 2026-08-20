"""Bodiless responses (HEAD, 1xx, 204, 304) send only headers on the wire.

A client stops reading these responses at the header block. Before this
was enforced, an app body on a 204 went out unframed after the headers
on a keep-alive connection, and a pooling router (Heroku Router 2.0)
parsed those bytes as the start of the NEXT response — intermittent 503s
(H17/H99) that the app never saw. HEAD had the same hole: the full GET
body went out on every HEAD to a body-returning view.

Response construction refuses bodiless statuses with a body (and rejects
1xx outright), so these tests reach the writers through the one path
construction can't see — status_code mutated after construction — plus
HEAD, where the app body is legitimate and the transport strips it.

The poisoning tests are the regression tests for the production
incident: after a bodiless response, the next bytes on the connection
must be the next response's status line.
"""

from __future__ import annotations

import asyncio
import logging

import h2.events
import pytest
from plain.http import AsyncStreamingResponse, Response
from server_stubs import H1Client, ResponseHandler, h1_connect, h2_connect, make_worker

_GET = b"GET / HTTP/1.1\r\nHost: testserver\r\n\r\n"
_HEAD = b"HEAD / HTTP/1.1\r\nHost: testserver\r\n\r\n"


def _mutated_204() -> Response:
    # The path construction-time enforcement can't see: the status is
    # changed after the body was set.
    response = Response(b"leaked body bytes", content_type="text/plain")
    response.status_code = 204
    return response


async def _assert_next_response_clean(client: H1Client) -> None:
    """The regression assertion: request 2 on the same connection parses
    cleanly, i.e. nothing extra followed the previous header block."""
    await client.send(_GET)
    headers = await client.read_headers()
    assert headers.startswith(b"HTTP/1.1 ")


def _dropped_body_warnings(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [
        record
        for record in caplog.records
        if record.getMessage() == "Response body dropped for bodiless status"
    ]


def test_h1_204_body_dropped_and_connection_not_poisoned() -> None:
    async def scenario() -> None:
        worker = make_worker(handler=ResponseHandler(_mutated_204))
        client = await h1_connect(worker)
        try:
            await client.send(_GET)
            headers = await client.read_headers()

            assert headers.startswith(b"HTTP/1.1 204")
            assert b"leaked" not in headers
            lower = headers.lower()
            assert b"content-length" not in lower
            assert b"transfer-encoding" not in lower
            assert b"connection: keep-alive" in lower

            await _assert_next_response_clean(client)
        finally:
            client.teardown()

    asyncio.run(scenario())


def test_h1_204_app_content_length_stripped() -> None:
    def make_response() -> Response:
        response = _mutated_204()
        response.headers["Content-Length"] = "17"
        return response

    async def scenario() -> None:
        worker = make_worker(handler=ResponseHandler(make_response))
        client = await h1_connect(worker)
        try:
            await client.send(_GET)
            headers = await client.read_headers()
            assert headers.startswith(b"HTTP/1.1 204")
            assert b"content-length" not in headers.lower()
            await _assert_next_response_clean(client)
        finally:
            client.teardown()

    asyncio.run(scenario())


def test_h1_head_body_stripped_and_connection_not_poisoned() -> None:
    # HEAD falls back to get() at the view layer, so the app response
    # legitimately carries the full GET body — the transport strips it.
    async def scenario() -> None:
        worker = make_worker(
            handler=ResponseHandler(
                lambda: Response(b"hello world", content_type="text/plain")
            )
        )
        client = await h1_connect(worker)
        try:
            await client.send(_HEAD)
            headers = await client.read_headers()

            assert headers.startswith(b"HTTP/1.1 200")
            assert b"hello" not in headers
            lower = headers.lower()
            assert b"transfer-encoding" not in lower
            assert b"connection: keep-alive" in lower

            await _assert_next_response_clean(client)
        finally:
            client.teardown()

    asyncio.run(scenario())


def test_h1_head_app_content_length_preserved() -> None:
    # RFC 9110 allows Content-Length on a HEAD response — it describes
    # what a GET would have returned.
    def make_response() -> Response:
        response = Response(b"hello world", content_type="text/plain")
        response.headers["Content-Length"] = "11"
        return response

    async def scenario() -> None:
        worker = make_worker(handler=ResponseHandler(make_response))
        client = await h1_connect(worker)
        try:
            await client.send(_HEAD)
            headers = await client.read_headers()
            assert headers.startswith(b"HTTP/1.1 200")
            assert b"content-length: 11" in headers.lower()
            await _assert_next_response_clean(client)
        finally:
            client.teardown()

    asyncio.run(scenario())


def test_h1_304_content_length_preserved_no_body() -> None:
    def make_response() -> Response:
        response = Response(status_code=304)
        response.headers["Content-Length"] = "11"
        return response

    async def scenario() -> None:
        worker = make_worker(handler=ResponseHandler(make_response))
        client = await h1_connect(worker)
        try:
            await client.send(_GET)
            headers = await client.read_headers()
            assert headers.startswith(b"HTTP/1.1 304")
            assert b"content-length: 11" in headers.lower()
            await _assert_next_response_clean(client)
        finally:
            client.teardown()

    asyncio.run(scenario())


def test_h1_1xx_not_chunked() -> None:
    def make_response() -> Response:
        response = Response()
        response.status_code = 101
        # Forbidden on 1xx (RFC 9110 8.6) — must be stripped on the wire.
        response.headers["Content-Length"] = "5"
        return response

    async def scenario() -> None:
        worker = make_worker(handler=ResponseHandler(make_response))
        client = await h1_connect(worker)
        try:
            await client.send(_GET)
            headers = await client.read_headers()
            assert headers.startswith(b"HTTP/1.1 101")
            lower = headers.lower()
            assert b"transfer-encoding" not in lower
            assert b"content-length" not in lower
        finally:
            client.teardown()

    asyncio.run(scenario())


def test_h1_head_early_413_has_no_body() -> None:
    # A HEAD request rejected before its body is read (declared
    # Content-Length over the limit) gets a bodiless 413 — the error
    # writer honors HEAD like the response writers do.
    async def scenario() -> None:
        worker = make_worker(
            handler=ResponseHandler(lambda: Response(b"ok", content_type="text/plain"))
        )
        worker.max_request_body = 100
        client = await h1_connect(worker)
        try:
            await client.send(
                b"HEAD / HTTP/1.1\r\nHost: testserver\r\nContent-Length: 5000\r\n\r\n"
            )
            headers = await client.read_headers()
            assert headers.startswith(b"HTTP/1.1 413")
            assert b"content-length" in headers.lower()
            # Half-close so the server's linger sees EOF and exits, then
            # drain: anything after the header block would be the
            # (forbidden) body.
            client.writer.write_eof()
            await asyncio.wait_for(client.server_task, timeout=5)
            client.conn.close()
            extra = await asyncio.wait_for(client.reader.read(4096), timeout=5)
            assert extra == b""
        finally:
            client.teardown()

    asyncio.run(scenario())


def test_h1_head_unparseable_request_gets_bodiless_error() -> None:
    # HEAD-ness is latched from the request line before parsing, so even
    # an error response to a request that failed to parse is bodiless.
    async def scenario() -> None:
        worker = make_worker(
            handler=ResponseHandler(lambda: Response(b"ok", content_type="text/plain"))
        )
        client = await h1_connect(worker)
        try:
            # Obsolete header folding — rejected at parse time.
            await client.send(
                b"HEAD / HTTP/1.1\r\nHost: testserver\r\nX-Foo: a\r\n b\r\n\r\n"
            )
            headers = await client.read_headers()
            assert headers.startswith(b"HTTP/1.1 400")
            assert b"content-length" in headers.lower()
            client.writer.write_eof()
            await asyncio.wait_for(client.server_task, timeout=5)
            client.conn.close()
            extra = await asyncio.wait_for(client.reader.read(4096), timeout=5)
            assert extra == b""
        finally:
            client.teardown()

    asyncio.run(scenario())


def test_h1_head_healthcheck_has_no_body() -> None:
    async def scenario() -> None:
        worker = make_worker(
            handler=ResponseHandler(lambda: Response(b"ok", content_type="text/plain"))
        )
        worker.healthcheck_path_bytes = b"/up/"
        client = await h1_connect(worker)
        try:
            await client.send(b"HEAD /up/ HTTP/1.1\r\nHost: testserver\r\n\r\n")
            headers = await client.read_headers()
            assert headers.startswith(b"HTTP/1.1 200")
            # Content-Length describes the GET body; no body follows.
            assert b"content-length: 2" in headers.lower()
            client.writer.write_eof()
            await asyncio.wait_for(client.server_task, timeout=5)
            client.conn.close()
            extra = await asyncio.wait_for(client.reader.read(4096), timeout=5)
            assert extra == b""
        finally:
            client.teardown()

    asyncio.run(scenario())


def test_h1_head_on_sse_never_consumes_stream() -> None:
    # HEAD to an SSE view: headers only, and the (never-terminating)
    # generator must not be consumed — before the omits_body guard in
    # stream_async_response this iterated forever.
    consumed = []

    async def events():
        consumed.append(True)
        while True:
            yield b"data: tick\n\n"
            await asyncio.sleep(0.01)

    def make_response() -> Response:
        return AsyncStreamingResponse(events(), content_type="text/event-stream")

    async def scenario() -> None:
        worker = make_worker(handler=ResponseHandler(make_response))
        client = await h1_connect(worker)
        try:
            await client.send(_HEAD)
            headers = await client.read_headers()
            assert headers.startswith(b"HTTP/1.1 200")
            await asyncio.sleep(0.05)
            assert not consumed
        finally:
            client.teardown()

    asyncio.run(scenario())


def test_h1_dropped_body_warns_once(caplog: pytest.LogCaptureFixture) -> None:
    async def scenario() -> None:
        worker = make_worker(handler=ResponseHandler(_mutated_204))
        client = await h1_connect(worker)
        try:
            await client.send(_GET)
            headers = await client.read_headers()
            assert headers.startswith(b"HTTP/1.1 204")
        finally:
            client.teardown()

    with caplog.at_level(logging.WARNING, logger="plain.server.http.response"):
        asyncio.run(scenario())

    warnings = _dropped_body_warnings(caplog)
    assert len(warnings) == 1
    assert warnings[0].status == 204  # ty: ignore[unresolved-attribute]


def test_h1_head_strip_is_silent(caplog: pytest.LogCaptureFixture) -> None:
    # Even against a bodiless-status response with a body (the case that
    # warns on a non-HEAD request), HEAD stays silent — the app body is
    # legitimate there.
    async def scenario() -> None:
        worker = make_worker(handler=ResponseHandler(_mutated_204))
        client = await h1_connect(worker)
        try:
            await client.send(_HEAD)
            await client.read_headers()
        finally:
            client.teardown()

    with caplog.at_level(logging.WARNING, logger="plain.server.http.response"):
        asyncio.run(scenario())

    assert not _dropped_body_warnings(caplog)


def test_h2_204_headers_only_end_stream() -> None:
    def make_response() -> Response:
        response = _mutated_204()
        response.headers["Content-Length"] = "17"
        return response

    async def scenario() -> None:
        shutdown_event = asyncio.Event()
        client, server_task, executor = await h2_connect(
            ResponseHandler(make_response), shutdown_event
        )
        try:
            await client.request(1)
            headers = await client.response_headers(1)
            await client.wait_for(
                lambda e: isinstance(e, h2.events.StreamEnded) and e.stream_id == 1
            )
            assert headers[b":status"] == b"204"
            assert b"content-length" not in headers
            assert not [
                e for e in client.events if isinstance(e, h2.events.DataReceived)
            ]
        finally:
            client.writer.close()
            server_task.cancel()
            executor.shutdown(wait=False)

    asyncio.run(scenario())


def test_h2_head_headers_only_end_stream() -> None:
    async def scenario() -> None:
        shutdown_event = asyncio.Event()
        client, server_task, executor = await h2_connect(
            ResponseHandler(
                lambda: Response(b"hello world", content_type="text/plain")
            ),
            shutdown_event,
        )
        try:
            await client.request(1, method="HEAD")
            headers = await client.response_headers(1)
            await client.wait_for(
                lambda e: isinstance(e, h2.events.StreamEnded) and e.stream_id == 1
            )
            assert headers[b":status"] == b"200"
            assert not [
                e for e in client.events if isinstance(e, h2.events.DataReceived)
            ]
        finally:
            client.writer.close()
            server_task.cancel()
            executor.shutdown(wait=False)

    asyncio.run(scenario())
