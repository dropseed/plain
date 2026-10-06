"""The test client reads an AsyncStreamingResponse body with the same
`ResponseLifecycle` the server sends it through — the response itself is never
replaced, so its identity (status, headers, exception, reason) is what
span finalization and test assertions read afterwards."""

import contextvars
import time
from collections.abc import AsyncIterator

from opentelemetry import trace
from plain.http import AsyncStreamingResponse
from plain.internal.handlers.response_lifecycle import ResponseLifecycle
from plain.server.inprocess import SentResponse
from plain.testing import ClientResponse, build_request, raises


async def _stream() -> AsyncIterator[bytes]:
    yield b"data: 1\n\n"


def _read(response: AsyncStreamingResponse, *, method: str = "GET") -> bytes:
    request = build_request(method=method, path="/")
    lifecycle = ResponseLifecycle(
        response,
        request=request,
        context=contextvars.copy_context(),
        span=trace.INVALID_SPAN,
        started=time.perf_counter(),
        executor=None,
    )
    return lifecycle.read()


def test_read_keeps_the_response_itself() -> None:
    response = AsyncStreamingResponse(
        _stream(), content_type="text/event-stream", status_code=500
    )
    exc = RuntimeError("boom")
    response.exception = exc
    response._reason_phrase = "Custom Reason"

    content = _read(response)

    assert content == b"data: 1\n\n"
    assert response.status_code == 500
    assert response.headers["Content-Type"] == "text/event-stream"
    assert response.exception is exc
    assert response.reason_phrase == "Custom Reason"
    assert response.closed


def test_head_never_reads_the_stream() -> None:
    consumed: list[bool] = []

    async def endless() -> AsyncIterator[bytes]:
        consumed.append(True)
        while True:
            yield b"data: tick\n\n"

    response = AsyncStreamingResponse(endless(), content_type="text/event-stream")

    assert _read(response, method="HEAD") == b""
    assert consumed == []
    assert response.closed


def test_client_response_status_is_read_only() -> None:
    response = ClientResponse(
        SentResponse(
            request=build_request("GET", "/"),
            response=AsyncStreamingResponse(
                _stream(), content_type="text/event-stream"
            ),
            status_code=200,
            body=b"",
        )
    )
    with raises(AttributeError):
        response.status_code = 204  # ty: ignore[invalid-assignment]
