"""1xx, 204, and 304 responses never have a body (RFC 9110).

A client stops reading these responses at the header block, so body
bytes would corrupt the next response on a keep-alive connection.
Response refuses the contradiction at construction — the bug is caught
at the line that wrote it, not on the wire in production.
"""

import pytest
from plain.http import (
    AsyncStreamingResponse,
    JsonResponse,
    NotModifiedResponse,
    Response,
    StreamingResponse,
)


@pytest.mark.parametrize("status_code", [204, 304])
def test_bodiless_status_with_content_raises(status_code):
    with pytest.raises(ValueError, match="cannot have a body"):
        Response("some message", status_code=status_code)


@pytest.mark.parametrize("status_code", [204, 304])
def test_bodiless_status_without_content_is_fine(status_code):
    response = Response(status_code=status_code)
    assert response.status_code == status_code
    assert response.content == b""


@pytest.mark.parametrize("status_code", [100, 101, 199])
def test_1xx_status_rejected(status_code):
    # Interim responses belong to the server, not application code.
    with pytest.raises(ValueError, match="200 to 599"):
        Response(status_code=status_code)


def test_1xx_class_attribute_rejected():
    # The subclass class-attribute pattern (like NotModifiedResponse's
    # status_code = 304) is validated too.
    class EarlyResponse(Response):
        status_code = 103

    with pytest.raises(ValueError, match="200 to 599"):
        EarlyResponse()


def test_setting_content_after_bodiless_status_raises():
    response = Response(status_code=204)
    with pytest.raises(ValueError, match="cannot have a body"):
        response.content = b"late body"


def test_json_response_with_bodiless_status_raises():
    with pytest.raises(ValueError, match="cannot have a body"):
        JsonResponse({"detail": "deleted"}, status_code=204)


def test_not_modified_response_refuses_content():
    response = NotModifiedResponse()
    assert response.content == b""
    with pytest.raises(ValueError, match="cannot have a body"):
        response.content = b"body"


@pytest.mark.parametrize("status_code", [204, 304])
def test_streaming_response_bodiless_status_raises(status_code):
    # A stream on a bodiless status is always wrong — caught at
    # construction like the buffered case.
    with pytest.raises(ValueError, match="cannot have a body"):
        StreamingResponse(iter([b"chunk"]), status_code=status_code)


def test_async_streaming_response_bodiless_status_raises():
    async def agen():
        yield b"chunk"

    with pytest.raises(ValueError, match="cannot have a body"):
        AsyncStreamingResponse(agen(), status_code=204)


@pytest.mark.parametrize("status_code", [204, 304])
def test_bodiless_status_gets_no_default_content_type(status_code):
    # No representation to describe — and on a 304, caches update stored
    # representation headers from the response. Explicit values are kept.
    response = Response(status_code=status_code)
    assert "Content-Type" not in response.headers

    explicit = Response(status_code=status_code, content_type="application/json")
    assert explicit.headers["Content-Type"] == "application/json"


def test_regular_response_unaffected():
    response = Response("hello", status_code=200)
    assert response.content == b"hello"
    assert response.headers["Content-Type"] == "text/html; charset=utf-8"
