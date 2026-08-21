"""The test client collects an AsyncStreamingResponse into a plain
Response so tests can read `.content` — the rebuilt object must keep the
original's identity (status, headers, exception, reason), because span
finalization and test assertions read it afterwards."""

from __future__ import annotations

import pytest
from plain.http import AsyncStreamingResponse
from plain.test.client import ClientHandler


async def _stream():
    yield b"data: 1\n\n"


def _collect(response: AsyncStreamingResponse, *, consume: bool):
    handler = ClientHandler.__new__(ClientHandler)
    return handler._collect_async_streaming(response, consume=consume)


def test_collect_preserves_response_identity() -> None:
    response = AsyncStreamingResponse(
        _stream(), content_type="text/event-stream", status_code=500
    )
    exc = RuntimeError("boom")
    response.exception = exc
    response.log_access = False
    response._reason_phrase = "Custom Reason"

    collected = _collect(response, consume=True)

    assert collected.content == b"data: 1\n\n"
    assert collected.status_code == 500
    assert collected.headers["Content-Type"] == "text/event-stream"
    assert collected.exception is exc
    assert collected.log_access is False
    assert collected.reason_phrase == "Custom Reason"


class _MultiStatusStream(AsyncStreamingResponse):
    # Class-level declaration, no constructor argument — the effective
    # status must still survive collection.
    status_code = 207


def test_collect_preserves_class_declared_status() -> None:
    response = _MultiStatusStream(_stream(), content_type="text/event-stream")

    collected = _collect(response, consume=True)

    assert collected.status_code == 207
    assert collected.content == b"data: 1\n\n"


def test_client_response_wrapper_mirrors_readonly_status() -> None:
    # ClientResponse delegates response-owned attribute assignment to the
    # wrapped response, so the read-only status contract holds in tests.
    from plain.test.client import Client, ClientResponse

    response = AsyncStreamingResponse(_stream(), content_type="text/event-stream")
    wrapped = ClientResponse(response, Client())
    with pytest.raises(AttributeError):
        wrapped.status_code = 204
    # Test-only attributes still land on the wrapper.
    wrapped.redirect_chain = []
    assert wrapped.redirect_chain == []
