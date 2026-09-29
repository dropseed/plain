"""
System-level tests for the middleware pipeline.

These tests verify end-to-end behavior of the middleware chain,
including ordering, short-circuiting, exception handling, and
the interaction between builtin and user-defined middleware.
"""

from middleware_helpers import call_log, fresh_client
from plain.runtime import settings
from plain.test import Client

# Middleware pipeline basics
#
# Basic pipeline behavior.


def test_request_flows_through_to_view():
    """A normal request should reach the view and return its response."""
    client = Client()
    response = client.get("/")
    assert response.status_code == 200
    assert response.body == b"Hello, world!"


def test_response_has_content_length():
    """DefaultHeadersMiddleware should add Content-Length."""
    client = Client()
    response = client.get("/")
    assert "Content-Length" in response.headers
    assert response.headers["Content-Length"] == str(len(b"Hello, world!"))


# Host validation middleware
#
# Host validation middleware should reject invalid hosts.


def test_valid_host_passes():
    """Requests with valid hosts should pass through."""
    client = Client()
    response = client.get("/")
    assert response.status_code == 200


def test_invalid_host_returns_400():
    """Requests with invalid hosts should get 400 when ALLOWED_HOSTS is set."""
    original = settings.ALLOWED_HOSTS
    try:
        settings.ALLOWED_HOSTS = ["example.com"]
        client = fresh_client()
        response = client.get("/", headers={"Host": "evil.com"})
        assert response.status_code == 400
    finally:
        settings.ALLOWED_HOSTS = original


def test_empty_allowed_hosts_allows_all():
    """When ALLOWED_HOSTS is empty, all hosts are allowed."""
    original = settings.ALLOWED_HOSTS
    try:
        settings.ALLOWED_HOSTS = []
        client = fresh_client()
        response = client.get("/")
        assert response.status_code == 200
    finally:
        settings.ALLOWED_HOSTS = original


# Default headers middleware
#
# Default headers middleware runs after the view.


def test_custom_default_headers_applied():
    """DEFAULT_RESPONSE_HEADERS should be applied to responses."""
    original = settings.DEFAULT_RESPONSE_HEADERS
    try:
        settings.DEFAULT_RESPONSE_HEADERS = {
            "X-Test-Header": "test-value",
        }
        client = fresh_client()
        response = client.get("/")
        assert response.headers["X-Test-Header"] == "test-value"
    finally:
        settings.DEFAULT_RESPONSE_HEADERS = original


def test_view_headers_not_overridden():
    """Headers set by the view should not be overridden by defaults."""
    original = settings.DEFAULT_RESPONSE_HEADERS
    try:
        settings.DEFAULT_RESPONSE_HEADERS = {
            "Content-Type": "text/html; charset=utf-8",
        }
        client = fresh_client()
        response = client.get("/")
        # The view sets Content-Type, so the default should not override it
        assert "Content-Type" in response.headers
    finally:
        settings.DEFAULT_RESPONSE_HEADERS = original


# CSRF middleware
#
# CSRF middleware blocks cross-origin unsafe requests.


def test_get_requests_pass_csrf():
    """GET requests should always pass CSRF checks."""
    client = Client()
    response = client.get("/")
    assert response.status_code == 200


def test_post_without_origin_passes_csrf():
    """POST without Origin/Sec-Fetch-Site passes CSRF (non-browser)."""
    client = Client()
    response = client.post("/")
    # Should pass CSRF (no browser headers) — view may not support POST
    # but we shouldn't get a 400 from CSRF
    assert response.status_code != 400


def test_cross_origin_post_blocked():
    """POST with cross-site Sec-Fetch-Site should return 400."""
    client = fresh_client()
    response = client.post(
        "/",
        headers={"Sec-Fetch-Site": "cross-site"},
    )
    assert response.status_code == 400


# HTTPS redirect middleware
#
# HTTPS redirect middleware.


def test_no_https_redirect_when_disabled():
    """When HTTPS_REDIRECT_ENABLED is False, no redirect happens."""
    original = settings.HTTPS_REDIRECT_ENABLED
    try:
        settings.HTTPS_REDIRECT_ENABLED = False
        client = fresh_client()
        response = client.get("/")
        assert response.status_code == 200
    finally:
        settings.HTTPS_REDIRECT_ENABLED = original


def test_https_redirect_when_enabled():
    """When HTTPS_REDIRECT_ENABLED is True, HTTP requests get redirected."""
    original = settings.HTTPS_REDIRECT_ENABLED
    try:
        settings.HTTPS_REDIRECT_ENABLED = True
        client = fresh_client()
        # An http:// URL, to send a request that didn't come over HTTPS
        response = client.get("http://testserver/", follow_redirects=False)
        assert response.status_code == 301
        assert response.headers["Location"].startswith("https://")
    finally:
        settings.HTTPS_REDIRECT_ENABLED = original


# Exception handling
#
# Exceptions in middleware/views should be caught and converted to responses.


def test_view_exception_returns_500():
    """An unhandled exception in a view should return a 500 response."""
    from plain.urls.resolvers import _get_cached_resolver

    original_router = settings.URLS_ROUTER
    try:
        settings.URLS_ROUTER = "middleware_helpers.ErrorRouter"
        _get_cached_resolver.cache_clear()

        client = fresh_client()
        response = client.get("/")
        assert response.status_code == 500
    finally:
        settings.URLS_ROUTER = original_router
        _get_cached_resolver.cache_clear()


def test_middleware_exception_returns_500():
    """An exception in middleware should be caught and return 500."""
    original = settings.MIDDLEWARE
    try:
        settings.MIDDLEWARE = [
            "middleware_helpers.ExplodingMiddleware",
        ]
        client = fresh_client()
        response = client.get("/")
        assert response.status_code == 500
    finally:
        settings.MIDDLEWARE = original


# Middleware ordering
#
# Tests that middleware execute in the correct order.


def test_builtin_before_runs_before_user_middleware():
    """
    Builtin before-middleware runs before user middleware.
    Host validation rejects before user middleware ever runs.
    """
    call_log.clear()
    original_middleware = settings.MIDDLEWARE
    original_hosts = settings.ALLOWED_HOSTS
    try:
        settings.MIDDLEWARE = ["middleware_helpers.LoggingMiddleware"]
        settings.ALLOWED_HOSTS = ["example.com"]

        client = fresh_client()
        response = client.get("/", headers={"Host": "evil.com"})
        assert response.status_code == 400
        assert "user_middleware" not in call_log
    finally:
        settings.MIDDLEWARE = original_middleware
        settings.ALLOWED_HOSTS = original_hosts


def test_custom_middleware_wraps_view():
    """User middleware should be able to wrap the view call."""
    call_log.clear()
    original = settings.MIDDLEWARE
    try:
        settings.MIDDLEWARE = ["middleware_helpers.TrackingMiddleware"]

        client = fresh_client()
        response = client.get("/")
        assert response.status_code == 200
        assert call_log == ["before", "after"]
    finally:
        settings.MIDDLEWARE = original


def test_multiple_custom_middleware_order():
    """Multiple user middleware should execute in defined order (outermost first)."""
    call_log.clear()
    original = settings.MIDDLEWARE
    try:
        settings.MIDDLEWARE = [
            "middleware_helpers.FirstMiddleware",
            "middleware_helpers.SecondMiddleware",
        ]

        client = fresh_client()
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


def test_short_circuit_middleware_skips_inner():
    """A middleware that returns a response should prevent inner middleware from running."""
    call_log.clear()
    original = settings.MIDDLEWARE
    try:
        settings.MIDDLEWARE = [
            "middleware_helpers.BlockingMiddleware",
            "middleware_helpers.InnerMiddleware",
        ]

        client = fresh_client()
        response = client.get("/")
        assert response.status_code == 403
        assert response.body == b"blocked"
        assert call_log == ["blocking"]
    finally:
        settings.MIDDLEWARE = original


# Middleware unwinding
#
# Tests for the two-phase middleware model's unwinding behavior.
#
# The pipeline runs before_request forward through each middleware, then
# after_response in reverse. after_response ALWAYS runs for any middleware
# whose before_request completed, even if that middleware (or a later one)
# short-circuited.


def test_short_circuit_skips_outer_after():
    """
    Two-phase behavior: when inner middleware short-circuits by returning
    a response from before_request, outer middleware's after_response still
    runs because its before_request already completed.
    """
    call_log.clear()
    original = settings.MIDDLEWARE
    try:
        settings.MIDDLEWARE = [
            "middleware_helpers.OuterWrappingMiddleware",
            "middleware_helpers.BlockingMiddleware",
        ]

        client = fresh_client()
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


def test_exception_in_inner_middleware_is_converted_to_response():
    """
    When inner middleware raises in before_request, the exception is caught
    and converted to an error response. Outer middleware's after_response
    runs normally with that error response.
    """
    call_log.clear()
    original = settings.MIDDLEWARE
    try:
        settings.MIDDLEWARE = [
            "middleware_helpers.OuterWrappingMiddleware",
            "middleware_helpers.InnerExplodingMiddleware",
        ]

        client = fresh_client()
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


def test_exception_in_view_seen_by_middleware_after():
    """
    When the view raises, the exception is converted to an error response,
    and all middleware's after_response sees that response.
    """
    call_log.clear()
    from plain.urls.resolvers import _get_cached_resolver

    original_middleware = settings.MIDDLEWARE
    original_router = settings.URLS_ROUTER
    try:
        settings.MIDDLEWARE = [
            "middleware_helpers.OuterWrappingMiddleware",
        ]
        settings.URLS_ROUTER = "middleware_helpers.ErrorRouter"
        _get_cached_resolver.cache_clear()

        client = fresh_client()
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


def test_short_circuit_runs_teardown_in_same_middleware():
    """
    Two-phase behavior: after_response ALWAYS runs for any middleware
    whose before_request completed. Even when before_request short-circuits
    by returning a response, after_response still runs.
    """
    call_log.clear()
    original = settings.MIDDLEWARE
    try:
        settings.MIDDLEWARE = [
            "middleware_helpers.SetupTeardownMiddleware",
        ]

        # Normal request — both setup and teardown run
        client = fresh_client()
        response = client.get("/")
        assert response.status_code == 200
        assert call_log == ["setup", "teardown"]

        call_log.clear()

        # Short-circuit request — both setup and teardown run
        response = client.get("/", headers={"X-Block": "1"})
        assert response.status_code == 403
        assert call_log == ["setup", "teardown"]
    finally:
        settings.MIDDLEWARE = original


def test_after_middleware_can_modify_error_response():
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

        client = fresh_client()
        response = client.get("/")
        assert response.status_code == 500
        assert response.headers["X-Modified-By"] == "ResponseModifyingMiddleware"
    finally:
        settings.MIDDLEWARE = original_middleware
        settings.URLS_ROUTER = original_router
        _get_cached_resolver.cache_clear()


# SSE views
#
# Tests for ServerSentEventsView async dispatch and streaming.


def test_sse_view_streams_formatted_events():
    """ServerSentEventsView should format and stream events."""
    from plain.urls.resolvers import _get_cached_resolver

    original_router = settings.URLS_ROUTER
    try:
        settings.URLS_ROUTER = "middleware_helpers.SSERouter"
        _get_cached_resolver.cache_clear()

        client = fresh_client()
        response = client.get("/")
        assert response.status_code == 200
        assert "text/event-stream" in response.headers["Content-Type"]
        assert response.headers["Cache-Control"] == "no-cache"

        body = response.text
        # Three ServerSentEvent instances with different data types
        assert "data: hello\n\n" in body
        assert 'data: {"count": 1}\n\n' in body
        assert "event: finish\nid: msg-3\ndata: done\n\n" in body
    finally:
        settings.URLS_ROUTER = original_router
        _get_cached_resolver.cache_clear()


def test_sse_view_with_middleware_ordering():
    """Middleware before/after still runs correctly with SSE views."""
    call_log.clear()
    from plain.urls.resolvers import _get_cached_resolver

    original_middleware = settings.MIDDLEWARE
    original_router = settings.URLS_ROUTER
    try:
        settings.MIDDLEWARE = ["middleware_helpers.TrackingMiddleware"]
        settings.URLS_ROUTER = "middleware_helpers.SSERouter"
        _get_cached_resolver.cache_clear()

        client = fresh_client()
        response = client.get("/")
        assert response.status_code == 200
        assert call_log == ["before", "after"]
    finally:
        settings.MIDDLEWARE = original_middleware
        settings.URLS_ROUTER = original_router
        _get_cached_resolver.cache_clear()


def test_middleware_short_circuit_with_sse_view():
    """Middleware short-circuit should work even when the route is an SSE view."""
    from plain.urls.resolvers import _get_cached_resolver

    original_middleware = settings.MIDDLEWARE
    original_router = settings.URLS_ROUTER
    try:
        settings.MIDDLEWARE = ["middleware_helpers.BlockingMiddleware"]
        settings.URLS_ROUTER = "middleware_helpers.SSERouter"
        _get_cached_resolver.cache_clear()

        client = fresh_client()
        response = client.get("/")
        assert response.status_code == 403
        assert response.body == b"blocked"
    finally:
        settings.MIDDLEWARE = original_middleware
        settings.URLS_ROUTER = original_router
        _get_cached_resolver.cache_clear()
