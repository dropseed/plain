"""Tests for View lifecycle hooks: after_response chaining and
handle_exception logging semantics.
"""

from __future__ import annotations

import logging

import pytest

from plain.http import Response, ResponseBase
from plain.internal.handlers.exception import response_for_exception
from plain.test import RequestFactory
from plain.views import View


class _ListHandler(logging.Handler):
    """Captures records into a list regardless of logger propagation.

    We can't rely on pytest's `caplog` because `configure_logging` sets
    `propagate=False` on `plain` loggers; once another test has called
    it, records never reach caplog's root-attached handler.
    """

    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


@pytest.fixture
def request_log():
    # Import the exact logger instance used in `plain.logs.exceptions`.
    # `logging.getLogger("plain.request")` is not sufficient — another
    # test's cleanup may have removed the name from `loggerDict`, in
    # which case a fresh logger is created while the module-level
    # binding in `plain.logs.exceptions` still points at the old one.
    from plain.logs.exceptions import request_logger as logger

    handler = _ListHandler()
    previous_level = logger.level
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    try:
        yield handler
    finally:
        logger.removeHandler(handler)
        logger.setLevel(previous_level)


def _has_server_error(handler: _ListHandler) -> bool:
    return any("Server error" in r.getMessage() for r in handler.records)


class TestAfterResponseChaining:
    """Every non-base after_response override must call super() so mixins compose."""

    def test_two_mixins_both_run(self, caplog):
        class AHeader(View):
            def after_response(self, response: ResponseBase) -> ResponseBase:
                response = super().after_response(response)
                response.headers["X-A"] = "a"
                return response

        class BHeader(View):
            def after_response(self, response: ResponseBase) -> ResponseBase:
                response = super().after_response(response)
                response.headers["X-B"] = "b"
                return response

        class Composed(AHeader, BHeader):
            def get(self):
                return Response("hi")

        request = RequestFactory().get("/")
        response = Composed(request=request).get_response()
        assert response.headers.get("X-A") == "a"
        assert response.headers.get("X-B") == "b"

    def test_mro_order_is_leaf_first(self):
        """Outer mixin runs last (sees inner mixin's mutations)."""

        order: list[str] = []

        class Outer(View):
            def after_response(self, response: ResponseBase) -> ResponseBase:
                response = super().after_response(response)
                order.append("outer")
                return response

        class Inner(View):
            def after_response(self, response: ResponseBase) -> ResponseBase:
                response = super().after_response(response)
                order.append("inner")
                return response

        class Composed(Outer, Inner):
            def get(self):
                return Response("hi")

        Composed(request=RequestFactory().get("/")).get_response()
        assert order == ["inner", "outer"]

    def test_override_that_skips_super_short_circuits_chain(self):
        """Sanity: confirms the failure mode the fix is guarding against."""

        class Outer(View):
            def after_response(self, response: ResponseBase) -> ResponseBase:
                # Intentionally does NOT super() — proves regression shape.
                response.headers["X-Outer"] = "1"
                return response

        class Inner(View):
            def after_response(self, response: ResponseBase) -> ResponseBase:
                response = super().after_response(response)
                response.headers["X-Inner"] = "1"
                return response

        class Composed(Outer, Inner):
            def get(self):
                return Response("hi")

        response = Composed(request=RequestFactory().get("/")).get_response()
        assert response.headers.get("X-Outer") == "1"
        assert response.headers.get("X-Inner") is None


class TestHandleExceptionLogging:
    """handle_exception returning a response suppresses logging.
    Re-raising defers to the framework error renderer, which logs.
    """

    def test_mapped_4xx_does_not_log_server_error(self, request_log):
        class AppError(Exception):
            pass

        class MappedView(View):
            def get(self):
                raise AppError("nope")

            def handle_exception(self, exc: Exception) -> ResponseBase:
                if isinstance(exc, AppError):
                    return Response("bad", status_code=400)
                return super().handle_exception(exc)

        response = MappedView(request=RequestFactory().get("/")).get_response()

        assert response.status_code == 400
        assert not _has_server_error(request_log), (
            "handle_exception mapping to 4xx must not emit a Server error log"
        )

    def test_reraise_from_handle_exception_propagates(self):
        """Default handle_exception re-raises — exception escapes get_response."""

        class Boom(View):
            def get(self):
                raise RuntimeError("boom")

        with pytest.raises(RuntimeError, match="boom"):
            Boom(request=RequestFactory().get("/")).get_response()

    def test_framework_logs_reraised_exception(self, request_log):
        """When handle_exception re-raises and the framework catches it,
        response_for_exception logs a Server error."""

        class Boom(View):
            def get(self):
                raise RuntimeError("boom")

        request = RequestFactory().get("/")
        try:
            Boom(request=request).get_response()
        except Exception as exc:
            caught = exc
        else:
            raise AssertionError("expected RuntimeError to propagate")

        # Only call log_exception to avoid pulling in a real template;
        # response_for_exception's first line is log_exception.
        from plain.logs import log_exception

        log_exception(request, caught)

        server_errors = [
            r for r in request_log.records if "Server error" in r.getMessage()
        ]
        assert len(server_errors) == 1

    def test_log_exception_is_idempotent(self, request_log):
        """If a view calls log_exception and the framework also tries,
        the sentinel keeps it to one record."""

        from plain.logs import log_exception

        exc = RuntimeError("once")
        request = RequestFactory().get("/")

        log_exception(request, exc)
        log_exception(request, exc)
        response_for_exception(request, exc)

        server_errors = [
            r for r in request_log.records if "Server error" in r.getMessage()
        ]
        assert len(server_errors) == 1

    def test_response_exception_short_circuits_without_logging(self, request_log):
        """ResponseException is the sanctioned 'I already have a response' path."""

        from plain.views.exceptions import ResponseException

        class ViaResponseException(View):
            def get(self):
                raise ResponseException(Response("handled", status_code=418))

        response = ViaResponseException(
            request=RequestFactory().get("/")
        ).get_response()

        assert response.status_code == 418
        assert not request_log.records
