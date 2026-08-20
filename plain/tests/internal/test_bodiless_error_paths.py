"""Framework layers that build responses with bodies must respect
bodiless statuses (204/304), now that Response refuses the combination.
"""

from __future__ import annotations

from plain.http import HTTPException, NotModifiedResponse, Response
from plain.internal.handlers.exception import response_for_exception
from plain.internal.middleware.headers import DefaultHeadersMiddleware
from plain.test import RequestFactory


class _NotModifiedError(HTTPException):
    status_code = 304


class _NoContentError(HTTPException):
    status_code = 204


def test_error_renderer_bodiless_status_has_no_body():
    request = RequestFactory().get("/")
    for exc, status in ((_NotModifiedError(), 304), (_NoContentError(), 204)):
        response = response_for_exception(request, exc)
        assert response.status_code == status
        assert response.content == b""
        # No Content-Type either: on a 304 caches update stored
        # representation headers from the response (RFC 9110 15.4.5).
        assert "Content-Type" not in response.headers


def test_error_renderer_out_of_range_status_degrades_to_500():
    # A broken HTTPException subclass (1xx or nonsense status) must not
    # crash the last-resort renderer.
    class _TooEarlyError(HTTPException):
        status_code = 103

    request = RequestFactory().get("/")
    response = response_for_exception(request, _TooEarlyError())
    assert response.status_code == 500
    assert isinstance(response.exception, _TooEarlyError)


def test_error_renderer_regular_status_keeps_body():
    request = RequestFactory().get("/")

    class _TeapotError(HTTPException):
        status_code = 418

    response = response_for_exception(request, _TeapotError())
    assert response.status_code == 418
    assert response.content == b"418 I'm a Teapot"


def test_default_headers_middleware_no_content_length_on_bodiless():
    # RFC 9110 8.6: never generate CL on 204; on 304 it must describe the
    # 200's representation, so a synthesized 0 is always wrong.
    middleware = DefaultHeadersMiddleware()
    request = RequestFactory().get("/")

    for response in (NotModifiedResponse(), Response(status_code=204)):
        result = middleware.after_response(request, response)
        assert "Content-Length" not in result.headers

    regular = middleware.after_response(request, Response(b"hello"))
    assert regular.headers["Content-Length"] == "5"


def test_client_strips_content_length_on_204():
    # The test client mirrors the wire: the writers drop Content-Length
    # where forbidden (1xx/204) and keep it on HEAD/304.
    from plain.test.client import _conditional_content_removal

    request = RequestFactory().get("/")

    response = Response(status_code=204)
    response.headers["Content-Length"] = "0"
    stripped = _conditional_content_removal(request, response)
    assert "Content-Length" not in stripped.headers

    response = Response(status_code=304)
    response.headers["Content-Length"] = "11"
    kept = _conditional_content_removal(request, response)
    assert kept.headers["Content-Length"] == "11"
