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
