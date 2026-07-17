"""System tests for view exception handling.

The framework default returns plain text for any exception. `TemplateView`
overrides `handle_exception` to render `{status}.html`; subclasses
inherit that. Plain `View` doesn't override the hook, so exceptions
raised from a plain view fall through to the framework's plain-text
default. For URL-resolution failures (no view ever runs), mount
`NotFoundView` as a `path("<path:_>", ...)` catch-all to get the styled
404 there too.
"""

from __future__ import annotations

from contextlib import contextmanager

from plain.runtime import settings
from plain.test import Client, patch
from plain.urls.resolvers import _get_cached_resolver


@contextmanager
def _error_client():
    """Client routed to the error-raising views in `error_routers.py`."""
    original = settings.URLS_ROUTER
    original_debug = settings.DEBUG
    settings.URLS_ROUTER = "error_routers.ErrorRouter"
    settings.DEBUG = False
    _get_cached_resolver.cache_clear()
    try:
        client = Client(raise_request_exception=False)
        # Middleware chain was built on init with the old router; rebuild it
        # after the settings swap.
        client.handler._middleware_chain = None
        client.handler.load_middleware()
        yield client
    finally:
        settings.URLS_ROUTER = original
        settings.DEBUG = original_debug
        _get_cached_resolver.cache_clear()


class TestPlainViewFallsThroughToText:
    """A plain `View` re-raises; the framework default returns plain text."""

    def test_404_renders_plain_text(self):
        with _error_client() as error_client:
            response = error_client.get("/plain-404")
            assert response.status_code == 404
            assert response.headers["Content-Type"] == "text/plain; charset=utf-8"
            assert response.content == b"404 Not Found"

    def test_500_renders_plain_text(self):
        with _error_client() as error_client:
            response = error_client.get("/plain-500")
            assert response.status_code == 500
            assert response.headers["Content-Type"] == "text/plain; charset=utf-8"
            assert response.content == b"500 Internal Server Error"


class TestTemplateViewRendersHtml:
    """`TemplateView.handle_exception` renders `{status}.html`."""

    def test_404_renders_404_html(self):
        with _error_client() as error_client:
            response = error_client.get("/template-404")
            assert response.status_code == 404
            assert b"Test 404 page" in response.content

    def test_500_renders_500_html(self):
        with _error_client() as error_client:
            response = error_client.get("/template-500")
            assert response.status_code == 500
            assert b"Test 500 page" in response.content

    def test_403_without_matching_template_falls_back_to_text(self):
        """No 403.html → plain-text response with status + reason."""
        with _error_client() as error_client:
            response = error_client.get("/template-403")
            assert response.status_code == 403
            assert response.headers["Content-Type"] == "text/plain; charset=utf-8"
            assert response.content == b"403 Forbidden"


class TestNotFoundViewCatchAll:
    """`NotFoundView` mounted as `path("<path:_>", ...)` renders `404.html`
    for unmatched URLs — covering the URL-resolution-failure case that
    never reaches a user view.
    """

    def test_unknown_url_renders_404_html(self):
        with _error_client() as error_client:
            response = error_client.get("/no-such-path")
            assert response.status_code == 404
            assert b"Test 404 page" in response.content

    def test_post_to_unknown_url_is_404_not_405(self):
        """`before_request` raises before method dispatch, so non-GET methods
        get the same 404 instead of a 405 Method Not Allowed."""
        with _error_client() as error_client:
            response = error_client.post("/no-such-path", form_data={})
            assert response.status_code == 404
            assert b"Test 404 page" in response.content


class TestCustomHTTPExceptionSubclass:
    """User-defined HTTPException subclasses carry their own status_code."""

    def test_custom_402_renders_plain_text(self):
        with _error_client() as error_client:
            response = error_client.get("/plain-402")
            assert response.status_code == 402
            assert response.headers["Content-Type"] == "text/plain; charset=utf-8"
            assert response.content == b"402 Payment Required"


class TestRenderFailureFallsBackToText:
    """If `{status}.html` itself raises, the view returns a bare-status
    response and `response.exception` is stamped by `_respond_to_exception`
    so observability still records the original failure.
    """

    def test_broken_500_template_falls_back_to_text(self):
        from plain.templates import Template

        original_render = Template.render

        def boom_on_500(self, context=None):
            if self.template_name == "500.html":
                raise RuntimeError("render blew up")
            return original_render(self, context or {})

        with _error_client() as error_client, patch(Template, "render", boom_on_500):
            response = error_client.get("/template-500")
            assert response.status_code == 500
            assert response.content == b""
            assert response.exception is not None
