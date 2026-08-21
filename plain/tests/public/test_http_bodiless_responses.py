"""1xx, 204, and 304 responses never have a body (RFC 9110).

A client stops reading these responses at the header block, so body
bytes would corrupt the next response on a keep-alive connection.
Response refuses the contradiction at construction — the bug is caught
at the line that wrote it, not on the wire in production.
"""

import asyncio

import pytest
from plain.http import (
    AsyncStreamingResponse,
    FileResponse,
    HTTPException,
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


@pytest.mark.parametrize("status_code", [200, 204, 304])
def test_explicit_none_means_no_body(status_code):
    response = Response(None, status_code=status_code)
    assert response.content == b""


def test_1xx_http_exception_subclass_rejected_at_definition():
    # A broken HTTPException subclass fails at the line that wrote it,
    # not inside the error renderers at request time.
    with pytest.raises(ValueError, match="200 to 599"):

        class TooEarly(HTTPException):
            status_code = 103


@pytest.mark.parametrize("bad_status", [None, "404", True])
def test_non_int_response_subclass_rejected_at_definition(bad_status):
    # Response and HTTPException agree: an explicit `status_code = None`
    # is a (bad) declaration, not an omission.
    with pytest.raises(ValueError, match="200 to 599"):

        class BrokenResponse(Response):
            status_code = bad_status


@pytest.mark.parametrize("bad_status", [None, "404", True])
def test_non_int_http_exception_subclass_rejected_at_definition(bad_status):
    # Non-int statuses get the same clear ValueError, not an opaque
    # TypeError from the range comparison.
    with pytest.raises(ValueError, match="200 to 599"):

        class Broken(HTTPException):
            status_code = bad_status


def test_streaming_reject_leaves_iterator_with_caller():
    # The constructor refuses a bodiless status before ever taking
    # ownership of the iterator — the caller keeps it (and its cleanup
    # responsibility), untouched.
    class Iterator:
        closed = False

        def __iter__(self):
            return iter([b"x"])

        def close(self):
            self.closed = True

    iterator = Iterator()
    with pytest.raises(ValueError, match="streaming"):
        StreamingResponse(iterator, status_code=304)
    assert not iterator.closed
    assert list(iterator) == [b"x"]


def test_file_response_reject_closes_owned_handle(tmp_path):
    # Unlike a generic iterator, FileResponse owns the handle it's given
    # (the idiomatic call is FileResponse(open(p)) — the caller keeps no
    # reference), so rejection must close it.
    path = tmp_path / "f.txt"
    path.write_bytes(b"x")
    handle = open(path, "rb")  # noqa: SIM115 — FileResponse takes ownership
    with pytest.raises(ValueError, match="streaming"):
        FileResponse(handle, status_code=304)
    assert handle.closed


def test_async_streaming_reject_leaves_generator_with_caller():
    # The constructor refuses before taking ownership — a started async
    # generator remains the caller's to iterate or close.
    async def gen():
        yield b"x"
        yield b"y"

    async def scenario():
        agen = gen()
        assert await agen.__anext__() == b"x"
        with pytest.raises(ValueError, match="streaming"):
            AsyncStreamingResponse(agen, status_code=204)
        assert await agen.__anext__() == b"y"
        await agen.aclose()

    asyncio.run(scenario())


def test_not_modified_keeps_explicit_content_type():
    # Only the *default* Content-Type is skipped on a 304 — a header the
    # caller set deliberately goes out (RFC 9110 15.4.5 allows headers
    # meant to update a cache's stored representation).
    response = NotModifiedResponse(headers={"Content-Type": "text/html"})
    assert response.headers["Content-Type"] == "text/html"


@pytest.mark.parametrize("status_code", [100, 101, 199])
def test_1xx_status_rejected(status_code):
    # Interim responses belong to the server, not application code.
    with pytest.raises(ValueError, match="200 to 599"):
        Response(status_code=status_code)


def test_1xx_class_attribute_rejected_at_definition():
    # The subclass class-attribute pattern (like NotModifiedResponse's
    # status_code = 304) is validated when the class is defined.
    with pytest.raises(ValueError, match="200 to 599"):

        class EarlyResponse(Response):
            status_code = 103


def test_status_code_is_fixed_at_construction():
    # No setter — a status/body contradiction can never be created by
    # mutation, so the transports never have anything to clean up.
    # (Static checkers flag the assignment too.)
    response = Response(b"some body")
    with pytest.raises(AttributeError, match="status_code"):
        response.status_code = 204  # ty: ignore[invalid-assignment]


def test_not_modified_response_signature_is_pinned():
    # No content/status_code/content_type parameters — this class always
    # means exactly "bodiless 304".
    with pytest.raises(TypeError):
        NotModifiedResponse(status_code=200)  # ty: ignore[unknown-argument]


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
