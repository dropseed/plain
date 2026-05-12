"""Pin `RedirectSlashMiddleware` behavior at the middleware layer.

The user-facing contract pins live in `tests/public/test_urls_trailing_slash.py`.
This file pins one specific developer-help behavior — the
`RuntimeError` raised on POST/PUT/PATCH + missing slash + `DEBUG=True` —
that can't be tested via `Client()` because the 404 template render
attempt in DEBUG mode crashes the pipeline first (the test app doesn't
install `plain.templates`).

Step #2 of the URL routing arc replaces the 301 redirect with a 308
(which preserves POST), making the RuntimeError unnecessary. This test
flips to deletion at that point.
"""

from __future__ import annotations

import pytest

from plain.http import Response
from plain.internal.middleware.slash import RedirectSlashMiddleware
from plain.runtime import settings
from plain.test import RequestFactory
from plain.urls.resolvers import _get_cached_resolver


@pytest.fixture
def slash_routes():
    original_router = settings.URLS_ROUTER
    settings.URLS_ROUTER = "slash_routers.SlashRouter"
    _get_cached_resolver.cache_clear()
    try:
        yield
    finally:
        settings.URLS_ROUTER = original_router
        _get_cached_resolver.cache_clear()


def _run_middleware_after_404(request) -> Response:
    """Simulate the request reaching `after_response` with a 404."""
    response = Response(status_code=404)
    middleware = RedirectSlashMiddleware()
    return middleware.after_response(request, response)


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH"])
def test_debug_unsafe_method_without_slash_raises_runtime_error(slash_routes, method):
    """DEBUG=True + POST/PUT/PATCH + missing slash → RuntimeError.

    Today the middleware refuses to redirect any method that carries a body
    in DEBUG mode because the 301 would silently lose the body. Step #2
    swaps 301 → 308 (which preserves the method), making this guard
    unnecessary — the `RuntimeError` is deleted.
    """
    original_debug = settings.DEBUG
    settings.DEBUG = True
    try:
        request = RequestFactory().generic(
            method, "/with-slash", content_type="text/plain"
        )
        with pytest.raises(RuntimeError, match="APPEND_SLASH"):
            _run_middleware_after_404(request)
    finally:
        settings.DEBUG = original_debug


def test_debug_get_without_slash_redirects_normally(slash_routes):
    """DEBUG=True + GET + missing slash → 301 (no RuntimeError; only POST/PUT/PATCH guarded)."""
    original_debug = settings.DEBUG
    settings.DEBUG = True
    try:
        request = RequestFactory().get("/with-slash")
        response = _run_middleware_after_404(request)
        assert response.status_code == 301
        assert response.headers["Location"] == "/with-slash/"
    finally:
        settings.DEBUG = original_debug


def test_nondebug_post_without_slash_no_runtime_error(slash_routes):
    """DEBUG=False + POST + missing slash → 301 (no guard); pin the body-loss bug."""
    original_debug = settings.DEBUG
    settings.DEBUG = False
    try:
        request = RequestFactory().post("/with-slash", content_type="text/plain")
        response = _run_middleware_after_404(request)
        assert response.status_code == 301
        assert response.headers["Location"] == "/with-slash/"
    finally:
        settings.DEBUG = original_debug
