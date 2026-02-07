from __future__ import annotations

import pytest

from plain.assets.manifest import AssetsManifest
from plain.assets.views import AssetView
from plain.runtime import settings
from plain.test import RequestFactory


def make_asset_view(manifest: AssetsManifest, path: str) -> AssetView:
    """Create an AssetView with a test manifest."""

    class TestAssetView(AssetView):
        def get_manifest(self):
            return manifest

    rf = RequestFactory()
    request = rf.get(f"/assets/{path}")
    view = TestAssetView()
    view.setup(request, path=path)
    return view


@pytest.fixture
def manifest():
    """Create a manifest with test data.

    Simulates compiled assets:
    - css/style.css -> css/style.abc1234.css (fingerprinted)
    - js/app.js (non-fingerprinted)
    """
    m = AssetsManifest()
    m.add_fingerprinted("css/style.css", "css/style.abc1234.css")
    m.add_non_fingerprinted("js/app.js")
    return m


@pytest.fixture
def cdn_url():
    """Set ASSETS_CDN_URL for testing and restore after."""
    original = settings.ASSETS_CDN_URL
    settings.ASSETS_CDN_URL = "https://cdn.example.com/"
    yield settings.ASSETS_CDN_URL
    settings.ASSETS_CDN_URL = original


class TestAssetsManifest:
    """Tests for AssetsManifest class."""

    def test_is_fingerprinted_true_for_fingerprinted_path(self, manifest):
        assert manifest.is_fingerprinted("css/style.abc1234.css") is True

    def test_is_fingerprinted_false_for_original_path(self, manifest):
        assert manifest.is_fingerprinted("css/style.css") is False

    def test_is_fingerprinted_false_for_unknown_path(self, manifest):
        assert manifest.is_fingerprinted("unknown.css") is False

    def test_is_fingerprinted_false_for_non_fingerprinted_terminal(self, manifest):
        assert manifest.is_fingerprinted("js/app.js") is False

    def test_resolve_returns_fingerprinted_for_original(self, manifest):
        assert manifest.resolve("css/style.css") == "css/style.abc1234.css"

    def test_resolve_returns_same_path_for_terminal(self, manifest):
        assert manifest.resolve("css/style.abc1234.css") == "css/style.abc1234.css"
        assert manifest.resolve("js/app.js") == "js/app.js"

    def test_resolve_returns_none_for_unknown(self, manifest):
        assert manifest.resolve("unknown.css") is None


class TestAssetViewCdnRedirect:
    """Tests for AssetView.get_cdn_redirect_response()"""

    def test_not_in_manifest_returns_none(self, manifest):
        view = make_asset_view(manifest, "unknown.css")
        assert view.get_cdn_redirect_response("unknown.css") is None

    def test_original_path_302_redirects_to_fingerprinted(self, manifest, cdn_url):
        view = make_asset_view(manifest, "css/style.css")
        response = view.get_cdn_redirect_response("css/style.css")
        assert response is not None
        assert response.status_code == 302
        assert response.headers["Cache-Control"] == "max-age=60"
        assert (
            response.headers["Location"]
            == "https://cdn.example.com/css/style.abc1234.css"
        )

    def test_fingerprinted_terminal_301_redirects(self, manifest, cdn_url):
        view = make_asset_view(manifest, "css/style.abc1234.css")
        response = view.get_cdn_redirect_response("css/style.abc1234.css")
        assert response is not None
        assert response.status_code == 301
        assert response.headers["Cache-Control"] == "max-age=31536000, immutable"
        assert (
            response.headers["Location"]
            == "https://cdn.example.com/css/style.abc1234.css"
        )

    def test_non_fingerprinted_terminal_302_redirects(self, manifest, cdn_url):
        view = make_asset_view(manifest, "js/app.js")
        response = view.get_cdn_redirect_response("js/app.js")
        assert response is not None
        assert response.status_code == 302
        assert response.headers["Cache-Control"] == "max-age=60"
        assert response.headers["Location"] == "https://cdn.example.com/js/app.js"

    def test_cdn_url_without_trailing_slash(self, manifest):
        """CDN URL works correctly with or without trailing slash."""
        original = settings.ASSETS_CDN_URL
        settings.ASSETS_CDN_URL = "https://cdn.example.com"  # No trailing slash
        try:
            view = make_asset_view(manifest, "css/style.css")
            response = view.get_cdn_redirect_response("css/style.css")
            assert response is not None
            assert (
                response.headers["Location"]
                == "https://cdn.example.com/css/style.abc1234.css"
            )
        finally:
            settings.ASSETS_CDN_URL = original


class TestAssetViewLocalRedirect:
    """Tests for AssetView.get_redirect_response()

    Note: We only test the None cases because the redirect case calls reverse()
    which requires URL routing setup. The redirect logic is covered by CDN tests.
    """

    def test_terminal_path_returns_none(self, manifest):
        view = make_asset_view(manifest, "css/style.abc1234.css")
        assert view.get_redirect_response("css/style.abc1234.css") is None

    def test_unknown_path_returns_none(self, manifest):
        view = make_asset_view(manifest, "unknown.css")
        assert view.get_redirect_response("unknown.css") is None
