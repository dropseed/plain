"""
System-level tests for the middleware pipeline.

These tests verify end-to-end behavior of the middleware chain,
including ordering, short-circuiting, exception handling, and
the interaction between builtin and user-defined middleware.
"""

from __future__ import annotations

import pytest
from middleware_helpers import call_log

from plain.runtime import settings
from plain.test import Client


def _fresh_client():
    """Create a Client with a fresh middleware chain."""
    client = Client(raise_request_exception=False)
    client.handler._middleware_chain = None
    client.handler.load_middleware()
    return client


@pytest.fixture(autouse=True)
def _clear_call_log():
    call_log.clear()


class TestMiddlewarePipelineBasics:
    """Basic pipeline behavior."""

    def test_request_flows_through_to_view(self):
        """A normal request should reach the view and return its response."""
        client = Client()
        response = client.get("/")
        assert response.status_code == 200
        assert response.content == b"Hello, world!"

    def test_response_has_content_length(self):
        """DefaultHeadersMiddleware should add Content-Length."""
        client = Client()
        response = client.get("/")
        assert "Content-Length" in response.headers
        assert response.headers["Content-Length"] == str(len(b"Hello, world!"))


class TestHealthcheckMiddleware:
    """Healthcheck middleware should short-circuit before reaching the view."""

    def test_healthcheck_returns_200(self):
        """Healthcheck path should return 200 without hitting the view."""
        original = settings.HEALTHCHECK_PATH
        try:
            settings.HEALTHCHECK_PATH = "/_health"
            client = _fresh_client()
            response = client.get("/_health")
            assert response.status_code == 200
            assert response.content == b"ok"
        finally:
            settings.HEALTHCHECK_PATH = original

    def test_healthcheck_does_not_affect_other_paths(self):
        """Non-healthcheck paths should still reach the view."""
        original = settings.HEALTHCHECK_PATH
        try:
            settings.HEALTHCHECK_PATH = "/_health"
            client = _fresh_client()
            response = client.get("/")
            assert response.status_code == 200
            assert response.content == b"Hello, world!"
        finally:
            settings.HEALTHCHECK_PATH = original


class TestHostValidationMiddleware:
    """Host validation middleware should reject invalid hosts."""

    def test_valid_host_passes(self):
        """Requests with valid hosts should pass through."""
        client = Client()
        response = client.get("/")
        assert response.status_code == 200

    def test_invalid_host_returns_400(self):
        """Requests with invalid hosts should get 400 when ALLOWED_HOSTS is set."""
        original = settings.ALLOWED_HOSTS
        try:
            settings.ALLOWED_HOSTS = ["example.com"]
            client = _fresh_client()
            response = client.get("/", headers={"Host": "evil.com"})
            assert response.status_code == 400
        finally:
            settings.ALLOWED_HOSTS = original

    def test_empty_allowed_hosts_allows_all(self):
        """When ALLOWED_HOSTS is empty, all hosts are allowed."""
        original = settings.ALLOWED_HOSTS
        try:
            settings.ALLOWED_HOSTS = []
            client = _fresh_client()
            response = client.get("/")
            assert response.status_code == 200
        finally:
            settings.ALLOWED_HOSTS = original


class TestDefaultHeadersMiddleware:
    """Default headers middleware runs after the view."""

    def test_custom_default_headers_applied(self):
        """DEFAULT_RESPONSE_HEADERS should be applied to responses."""
        original = settings.DEFAULT_RESPONSE_HEADERS
        try:
            settings.DEFAULT_RESPONSE_HEADERS = {
                "X-Test-Header": "test-value",
            }
            client = _fresh_client()
            response = client.get("/")
            assert response.headers["X-Test-Header"] == "test-value"
        finally:
            settings.DEFAULT_RESPONSE_HEADERS = original

    def test_view_headers_not_overridden(self):
        """Headers set by the view should not be overridden by defaults."""
        original = settings.DEFAULT_RESPONSE_HEADERS
        try:
            settings.DEFAULT_RESPONSE_HEADERS = {
                "Content-Type": "text/html; charset=utf-8",
            }
            client = _fresh_client()
            response = client.get("/")
            # The view sets Content-Type, so the default should not override it
            assert "Content-Type" in response.headers
        finally:
            settings.DEFAULT_RESPONSE_HEADERS = original


class TestCsrfMiddleware:
    """CSRF middleware blocks cross-origin unsafe requests."""

    def test_get_requests_pass(self):
        """GET requests should always pass CSRF checks."""
        client = Client()
        response = client.get("/")
        assert response.status_code == 200

    def test_post_without_origin_passes_csrf(self):
        """POST without Origin/Sec-Fetch-Site passes CSRF (non-browser)."""
        client = Client()
        response = client.post("/")
        # Should pass CSRF (no browser headers) — view may not support POST
        # but we shouldn't get a 400 from CSRF
        assert response.status_code != 400

    def test_cross_origin_post_blocked(self):
        """POST with cross-site Sec-Fetch-Site should return 400."""
        client = _fresh_client()
        response = client.post(
            "/",
            headers={"Sec-Fetch-Site": "cross-site"},
        )
        assert response.status_code == 400


class TestHttpsRedirectMiddleware:
    """HTTPS redirect middleware."""

    def test_no_redirect_when_disabled(self):
        """When HTTPS_REDIRECT_ENABLED is False, no redirect happens."""
        original = settings.HTTPS_REDIRECT_ENABLED
        try:
            settings.HTTPS_REDIRECT_ENABLED = False
            client = _fresh_client()
            response = client.get("/")
            assert response.status_code == 200
        finally:
            settings.HTTPS_REDIRECT_ENABLED = original

    def test_redirect_when_enabled(self):
        """When HTTPS_REDIRECT_ENABLED is True, HTTP requests get redirected."""
        original = settings.HTTPS_REDIRECT_ENABLED
        try:
            settings.HTTPS_REDIRECT_ENABLED = True
            client = _fresh_client()
            # Must use secure=False to send an HTTP (not HTTPS) request
            response = client.get("/", follow=False, secure=False)
            assert response.status_code == 301
            assert response.headers["Location"].startswith("https://")
        finally:
            settings.HTTPS_REDIRECT_ENABLED = original


class TestExceptionHandling:
    """Exceptions in middleware/views should be caught and converted to responses."""

    def test_view_exception_returns_500(self):
        """An unhandled exception in a view should return a 500 response."""
        from plain.urls.resolvers import _get_cached_resolver

        original_router = settings.URLS_ROUTER
        try:
            settings.URLS_ROUTER = "middleware_helpers.ErrorRouter"
            _get_cached_resolver.cache_clear()

            client = _fresh_client()
            response = client.get("/")
            assert response.status_code == 500
        finally:
            settings.URLS_ROUTER = original_router
            _get_cached_resolver.cache_clear()

    def test_middleware_exception_returns_500(self):
        """An exception in middleware should be caught and return 500."""
        original = settings.MIDDLEWARE
        try:
            settings.MIDDLEWARE = [
                "middleware_helpers.ExplodingMiddleware",
            ]
            client = _fresh_client()
            response = client.get("/")
            assert response.status_code == 500
        finally:
            settings.MIDDLEWARE = original


class TestMiddlewareOrdering:
    """Tests that middleware execute in the correct order."""

    def test_builtin_before_runs_before_user_middleware(self):
        """
        Builtin before-middleware runs before user middleware.
        Host validation rejects before user middleware ever runs.
        """
        original_middleware = settings.MIDDLEWARE
        original_hosts = settings.ALLOWED_HOSTS
        try:
            settings.MIDDLEWARE = ["middleware_helpers.LoggingMiddleware"]
            settings.ALLOWED_HOSTS = ["example.com"]

            client = _fresh_client()
            response = client.get("/", headers={"Host": "evil.com"})
            assert response.status_code == 400
            assert "user_middleware" not in call_log
        finally:
            settings.MIDDLEWARE = original_middleware
            settings.ALLOWED_HOSTS = original_hosts

    def test_custom_middleware_wraps_view(self):
        """User middleware should be able to wrap the view call."""
        original = settings.MIDDLEWARE
        try:
            settings.MIDDLEWARE = ["middleware_helpers.TrackingMiddleware"]

            client = _fresh_client()
            response = client.get("/")
            assert response.status_code == 200
            assert call_log == ["before", "after"]
        finally:
            settings.MIDDLEWARE = original

    def test_multiple_custom_middleware_order(self):
        """Multiple user middleware should execute in defined order (outermost first)."""
        original = settings.MIDDLEWARE
        try:
            settings.MIDDLEWARE = [
                "middleware_helpers.FirstMiddleware",
                "middleware_helpers.SecondMiddleware",
            ]

            client = _fresh_client()
            response = client.get("/")
            assert response.status_code == 200
            assert call_log == [
                "first_before",
                "second_before",
                "second_after",
                "first_after",
            ]
        finally:
            settings.MIDDLEWARE = original

    def test_short_circuit_middleware_skips_inner(self):
        """A middleware that returns a response should prevent inner middleware from running."""
        original = settings.MIDDLEWARE
        try:
            settings.MIDDLEWARE = [
                "middleware_helpers.BlockingMiddleware",
                "middleware_helpers.InnerMiddleware",
            ]

            client = _fresh_client()
            response = client.get("/")
            assert response.status_code == 403
            assert response.content == b"blocked"
            assert call_log == ["blocking"]
        finally:
            settings.MIDDLEWARE = original


class TestOnionUnwinding:
    """
    Tests for the onion model's unwinding behavior.

    In the current model, each middleware wraps the next as a callable chain.
    The "after" code (after self.get_response()) only runs if get_response
    was called. These tests document the exact current semantics so the
    refactor can verify which behaviors change intentionally.
    """

    def test_short_circuit_skips_outer_after(self):
        """
        Current onion behavior: when inner middleware short-circuits (returns
        without calling get_response), outer middleware's after code still runs
        because it DID call get_response — it just got back a short-circuit
        response.
        """
        original = settings.MIDDLEWARE
        try:
            settings.MIDDLEWARE = [
                "middleware_helpers.OuterWrappingMiddleware",
                "middleware_helpers.BlockingMiddleware",
            ]

            client = _fresh_client()
            response = client.get("/")
            assert response.status_code == 403
            # Outer called get_response which returned the 403 from Blocking,
            # so outer's after code runs with that 403
            assert call_log == [
                "outer_before",
                "blocking",
                "outer_after:403",
            ]
        finally:
            settings.MIDDLEWARE = original

    def test_exception_in_inner_middleware_is_converted_to_response(self):
        """
        Current behavior: each middleware is wrapped in convert_exception_to_response.
        When inner middleware raises, the exception is caught and converted to a
        response BEFORE outer middleware sees it. Outer middleware's after code
        runs normally with the error response.
        """
        original = settings.MIDDLEWARE
        try:
            settings.MIDDLEWARE = [
                "middleware_helpers.OuterWrappingMiddleware",
                "middleware_helpers.InnerExplodingMiddleware",
            ]

            client = _fresh_client()
            response = client.get("/")
            assert response.status_code == 500
            # Inner raised, converted to 500 response, outer sees it
            assert call_log == [
                "outer_before",
                "inner_explode_before",
                "outer_after:500",
            ]
        finally:
            settings.MIDDLEWARE = original

    def test_exception_in_view_seen_by_middleware_after(self):
        """
        When the view raises, convert_exception_to_response converts it to
        an error response, and all middleware's after code sees that response.
        """
        from plain.urls.resolvers import _get_cached_resolver

        original_middleware = settings.MIDDLEWARE
        original_router = settings.URLS_ROUTER
        try:
            settings.MIDDLEWARE = [
                "middleware_helpers.OuterWrappingMiddleware",
            ]
            settings.URLS_ROUTER = "middleware_helpers.ErrorRouter"
            _get_cached_resolver.cache_clear()

            client = _fresh_client()
            response = client.get("/")
            assert response.status_code == 500
            assert call_log == [
                "outer_before",
                "outer_after:500",
            ]
        finally:
            settings.MIDDLEWARE = original_middleware
            settings.URLS_ROUTER = original_router
            _get_cached_resolver.cache_clear()

    def test_short_circuit_skips_teardown_in_same_middleware(self):
        """
        Current onion behavior: when a middleware short-circuits (returns
        without calling get_response), its own after-get_response code
        never runs because the code path skips past it.

        This is the key semantic difference with the before/after refactor,
        where after_response ALWAYS runs for any middleware whose
        before_request ran. Update this test when the refactor lands.
        """
        original = settings.MIDDLEWARE
        try:
            settings.MIDDLEWARE = [
                "middleware_helpers.SetupTeardownMiddleware",
            ]

            # Normal request — both setup and teardown run
            client = _fresh_client()
            response = client.get("/")
            assert response.status_code == 200
            assert call_log == ["setup", "teardown"]

            call_log.clear()

            # Short-circuit request — only setup runs, teardown skipped
            response = client.get("/", headers={"X-Block": "1"})
            assert response.status_code == 403
            assert call_log == ["setup"]
            assert "teardown" not in call_log
        finally:
            settings.MIDDLEWARE = original

    def test_after_middleware_can_modify_error_response(self):
        """
        Middleware that runs after the view should be able to modify error
        responses — e.g. adding headers to a 500.
        """
        from plain.urls.resolvers import _get_cached_resolver

        original_middleware = settings.MIDDLEWARE
        original_router = settings.URLS_ROUTER
        try:
            settings.MIDDLEWARE = [
                "middleware_helpers.ResponseModifyingMiddleware",
            ]
            settings.URLS_ROUTER = "middleware_helpers.ErrorRouter"
            _get_cached_resolver.cache_clear()

            client = _fresh_client()
            response = client.get("/")
            assert response.status_code == 500
            assert response.headers["X-Modified-By"] == "ResponseModifyingMiddleware"
        finally:
            settings.MIDDLEWARE = original_middleware
            settings.URLS_ROUTER = original_router
            _get_cached_resolver.cache_clear()
