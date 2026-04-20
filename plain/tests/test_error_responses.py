"""System tests for view exception handling.

The framework default renders `{status}.html` for any exception — from a
`TemplateView`, a plain `View` that re-raises, URL resolution failure,
or middleware. Views that want a non-HTML format (like `APIView`)
override `handle_exception` to opt out. Plain-text fallback kicks in
only when the template is missing or fails to render.
"""

from __future__ import annotations

import pytest

from plain.runtime import settings
from plain.test import Client
from plain.urls.resolvers import _get_cached_resolver


@pytest.fixture
def error_client():
    """Client routed to the error-raising views in `error_routers.py`."""
    original = settings.URLS_ROUTER
    original_debug = settings.DEBUG
    settings.URLS_ROUTER = "error_routers.ErrorRouter"
    settings.DEBUG = False
    _get_cached_resolver.cache_clear()
    try:
        client = Client(raise_request_exception=False)
        # Middleware chain was built on init with the old router;
        # rebuild it after the settings swap.
        client.handler._middleware_chain = None
        client.handler.load_middleware()
        yield client
    finally:
        settings.URLS_ROUTER = original
        settings.DEBUG = original_debug
        _get_cached_resolver.cache_clear()


class TestPlainViewRendersHtml:
    """A plain `View` re-raises; the framework renders `{status}.html`."""

    def test_404_renders_404_html(self, error_client):
        response = error_client.get("/plain-404/")
        assert response.status_code == 404
        assert b"Test 404 page" in response.content

    def test_500_renders_500_html(self, error_client):
        response = error_client.get("/plain-500/")
        assert response.status_code == 500
        assert b"Test 500 page" in response.content


class TestTemplateViewRendersHtml:
    """Same as plain `View` — no separate handle_exception needed."""

    def test_404_renders_404_html(self, error_client):
        response = error_client.get("/template-404/")
        assert response.status_code == 404
        assert b"Test 404 page" in response.content

    def test_500_renders_500_html(self, error_client):
        response = error_client.get("/template-500/")
        assert response.status_code == 500
        assert b"Test 500 page" in response.content

    def test_403_without_matching_template_falls_back_to_text(self, error_client):
        """No 403.html → plain-text response with status + reason."""
        response = error_client.get("/template-403/")
        assert response.status_code == 403
        assert response.headers["Content-Type"] == "text/plain; charset=utf-8"
        assert response.content == b"403 Forbidden"


class TestUnknownUrlRendersHtml:
    """URL resolution failures happen before any view — still get `404.html`."""

    def test_unknown_url_renders_404_html(self, error_client):
        response = error_client.get("/no-such-path/")
        assert response.status_code == 404
        assert b"Test 404 page" in response.content


class TestCustomHTTPExceptionSubclass:
    """User-defined HTTPException subclasses carry their own status_code."""

    def test_custom_402_falls_back_to_text(self, error_client):
        response = error_client.get("/plain-402/")
        assert response.status_code == 402
        assert response.headers["Content-Type"] == "text/plain; charset=utf-8"
        assert response.content == b"402 Payment Required"


class TestRenderFailureFallsBackToText:
    """If `{status}.html` itself raises, we fall back without recursing."""

    def test_broken_500_template_falls_back_to_text(self, error_client, monkeypatch):
        from plain.templates import Template

        original_render = Template.render

        def boom_on_500(self, context=None):
            if self.template_name == "500.html":
                raise RuntimeError("render blew up")
            return original_render(self, context or {})

        monkeypatch.setattr(Template, "render", boom_on_500)

        response = error_client.get("/template-500/")
        assert response.status_code == 500
        # Template render raised (not TemplateFileMissing), so we get a
        # bare-status Response with the original exception attached.
        assert response.content == b""
        assert response.exception is not None
