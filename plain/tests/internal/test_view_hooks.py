"""Tests for View lifecycle hooks: after_response chaining and
handle_exception logging semantics.
"""

import logging

from plain.http import Response
from plain.internal.handlers.exception import response_for_exception
from plain.testing import CapturedLogs, build_request, capture_logs, patch, raises
from plain.views import View


def _has_server_error(logs: CapturedLogs) -> bool:
    return any("Server error" in message for message in logs.messages)


# After response chaining
#
# Every non-base after_response override must call super() so mixins compose.
def test_two_mixins_both_run():
    class AHeader(View):
        def after_response(self, response: Response) -> Response:
            response = super().after_response(response)
            response.headers["X-A"] = "a"
            return response

    class BHeader(View):
        def after_response(self, response: Response) -> Response:
            response = super().after_response(response)
            response.headers["X-B"] = "b"
            return response

    class Composed(AHeader, BHeader):
        def get(self):
            return Response("hi")

    request = build_request("GET", "/")
    response = Composed(request=request).get_response()
    assert response.headers.get("X-A") == "a"
    assert response.headers.get("X-B") == "b"


def test_mro_order_is_leaf_first():
    """Outer mixin runs last (sees inner mixin's mutations)."""

    order: list[str] = []

    class Outer(View):
        def after_response(self, response: Response) -> Response:
            response = super().after_response(response)
            order.append("outer")
            return response

    class Inner(View):
        def after_response(self, response: Response) -> Response:
            response = super().after_response(response)
            order.append("inner")
            return response

    class Composed(Outer, Inner):
        def get(self):
            return Response("hi")

    Composed(request=build_request("GET", "/")).get_response()
    assert order == ["inner", "outer"]


def test_override_that_skips_super_short_circuits_chain():
    """Sanity: confirms the failure mode the fix is guarding against."""

    class Outer(View):
        def after_response(self, response: Response) -> Response:
            # Intentionally does NOT super() — proves regression shape.
            response.headers["X-Outer"] = "1"
            return response

    class Inner(View):
        def after_response(self, response: Response) -> Response:
            response = super().after_response(response)
            response.headers["X-Inner"] = "1"
            return response

    class Composed(Outer, Inner):
        def get(self):
            return Response("hi")

    response = Composed(request=build_request("GET", "/")).get_response()
    assert response.headers.get("X-Outer") == "1"
    assert response.headers.get("X-Inner") is None


# Handle exception logging
#
# handle_exception returning a 4xx response suppresses logging and exception
# attachment (the view handled it). Returning a 5xx is treated as a real
# failure: the framework logs and attaches `response.exception` so subclasses
# don't each have to. Re-raising defers to the framework error renderer.
def test_mapped_4xx_does_not_log_server_error():
    with capture_logs("plain.request") as log:

        class AppError(Exception):
            pass

        class MappedView(View):
            def get(self):
                raise AppError("nope")

            def handle_exception(self, exc: Exception) -> Response:
                if isinstance(exc, AppError):
                    return Response("bad", status_code=400)
                return super().handle_exception(exc)

        response = MappedView(request=build_request("GET", "/")).get_response()

        assert response.status_code == 400
        assert response.exception is None
    assert not _has_server_error(log), (
        "handle_exception mapping to 4xx must not emit a Server error log"
    )


def test_mapped_5xx_logs_and_attaches_exception():
    """A subclass that maps to a 5xx response gets logging and exception
    attachment from the framework — no need to call log_exception or set
    response.exception in the override."""

    with capture_logs("plain.request") as log:

        class AppError(Exception):
            pass

        class MappedView(View):
            def get(self):
                raise AppError("boom")

            def handle_exception(self, exc: Exception) -> Response:
                if isinstance(exc, AppError):
                    return Response("oops", status_code=500)
                return super().handle_exception(exc)

        response = MappedView(request=build_request("GET", "/")).get_response()

        assert response.status_code == 500
        assert isinstance(response.exception, AppError)
    assert _has_server_error(log)


def test_reraise_from_handle_exception_propagates():
    """Default handle_exception re-raises — exception escapes get_response."""

    class Boom(View):
        def get(self):
            raise RuntimeError("boom")

    with raises(RuntimeError, match="boom"):
        Boom(request=build_request("GET", "/")).get_response()


def test_framework_logs_reraised_exception():
    """When handle_exception re-raises and the framework catches it,
    response_for_exception logs a Server error."""

    with capture_logs("plain.request") as log:

        class Boom(View):
            def get(self):
                raise RuntimeError("boom")

        request = build_request("GET", "/")
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

    server_errors = [r for r in log if "Server error" in r.getMessage()]
    assert len(server_errors) == 1


def test_falls_back_to_plain_text_when_templates_not_registered():
    """`plain.templates` importable but not in INSTALLED_PACKAGES → plain text.

    Pins the registry-label guard added to handle the "monorepo dev mode"
    case where the package is on the Python path but never registered.
    Simulated here by stubbing the registry lookup directly so the test
    works in any runner (isolated or dev).
    """
    from plain.packages import packages_registry

    def _missing(label: str):
        raise LookupError(label)

    with patch(packages_registry, "get_package_config", _missing):
        request = build_request("GET", "/")
        response = response_for_exception(request, RuntimeError("boom"))

    assert response.status_code == 500
    assert response.headers["Content-Type"] == "text/plain; charset=utf-8"
    assert response.content == b"500 Internal Server Error"
    # 5xx still carries the original exception for downstream tooling.
    assert response.exception.args == ("boom",)  # ty: ignore[unresolved-attribute]


def test_log_exception_is_idempotent():
    """If a view calls log_exception and the framework also tries,
    the sentinel keeps it to one record."""

    with capture_logs("plain.request") as log:
        from plain.logs import log_exception

        exc = RuntimeError("once")
        request = build_request("GET", "/")

        log_exception(request, exc)
        log_exception(request, exc)
        response_for_exception(request, exc)

    server_errors = [r for r in log if "Server error" in r.getMessage()]
    assert len(server_errors) == 1


def test_suspicious_operation_logs_at_warning_without_exc_info():
    """CSRF rejections and other SuspiciousOperationError400s are working-as-designed
    responses to scanner/probe traffic. They log on `plain.security.*` at WARNING
    without exc_info so Sentry's logging integration doesn't treat them as ERRORs."""

    from plain.http import SuspiciousOperationError400
    from plain.logs import log_exception

    with capture_logs("plain.security") as logs:
        log_exception(
            build_request("GET", "/api/app/config"),
            SuspiciousOperationError400("CSRF rejected"),
        )

    assert len(logs) == 1
    record = logs[0]
    assert record.levelno == logging.WARNING
    assert record.exc_info is None
    assert record.name == "plain.security.SuspiciousOperationError400"


def test_response_exception_short_circuits_without_logging():
    """ResponseException is the sanctioned 'I already have a response' path."""

    with capture_logs("plain.request") as log:
        from plain.views.exceptions import ResponseException

        class ViaResponseException(View):
            def get(self):
                raise ResponseException(Response("handled", status_code=418))

        response = ViaResponseException(
            request=build_request("GET", "/")
        ).get_response()

        assert response.status_code == 418
    assert not log
