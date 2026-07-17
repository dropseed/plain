from __future__ import annotations

from plain.assets.manifest import AssetsManifest
from plain.assets.views import AssetView
from plain.test import RequestFactory, override_settings


def make_asset_view(manifest: AssetsManifest, path: str) -> AssetView:
    """Create an AssetView with a test manifest."""

    class TestAssetView(AssetView):
        def get_manifest(self):
            return manifest

    rf = RequestFactory()
    request = rf.get(f"/assets/{path}")
    view = TestAssetView(request=request, url_kwargs={"path": path})
    return view


def make_manifest() -> AssetsManifest:
    """Create a manifest with test data.

    Simulates compiled assets:
    - css/style.css -> css/style.abc1234.css (fingerprinted)
    - js/app.js (non-fingerprinted)
    """
    m = AssetsManifest()
    m.add_fingerprinted("css/style.css", "css/style.abc1234.css")
    m.add_non_fingerprinted("js/app.js")
    return m


class TestAssetsManifest:
    """Tests for AssetsManifest class."""

    def test_is_immutable_true_for_fingerprinted_path(self):
        manifest = make_manifest()
        assert manifest.is_immutable("css/style.abc1234.css") is True

    def test_is_immutable_false_for_original_path(self):
        manifest = make_manifest()
        assert manifest.is_immutable("css/style.css") is False

    def test_is_immutable_false_for_unknown_path(self):
        manifest = make_manifest()
        assert manifest.is_immutable("unknown.css") is False

    def test_is_immutable_false_for_non_fingerprinted_terminal(self):
        manifest = make_manifest()
        assert manifest.is_immutable("js/app.js") is False

    def test_resolve_returns_fingerprinted_for_original(self):
        manifest = make_manifest()
        assert manifest.resolve("css/style.css") == "css/style.abc1234.css"

    def test_resolve_returns_same_path_for_terminal(self):
        manifest = make_manifest()
        assert manifest.resolve("css/style.abc1234.css") == "css/style.abc1234.css"
        assert manifest.resolve("js/app.js") == "js/app.js"

    def test_resolve_returns_none_for_unknown(self):
        manifest = make_manifest()
        assert manifest.resolve("unknown.css") is None


class TestAssetViewCdnRedirect:
    """Tests for AssetView.get_cdn_redirect_response()"""

    def test_not_in_manifest_returns_none(self):
        manifest = make_manifest()
        view = make_asset_view(manifest, "unknown.css")
        assert view.get_cdn_redirect_response("unknown.css") is None

    def test_original_path_302_redirects_to_fingerprinted(self):
        manifest = make_manifest()
        with override_settings(ASSETS_CDN_URL="https://cdn.example.com/"):
            view = make_asset_view(manifest, "css/style.css")
            response = view.get_cdn_redirect_response("css/style.css")
            assert response is not None
            assert response.status_code == 302
            assert response.headers["Cache-Control"] == "max-age=60"
            assert (
                response.headers["Location"]
                == "https://cdn.example.com/css/style.abc1234.css"
            )

    def test_fingerprinted_terminal_301_redirects(self):
        manifest = make_manifest()
        with override_settings(ASSETS_CDN_URL="https://cdn.example.com/"):
            view = make_asset_view(manifest, "css/style.abc1234.css")
            response = view.get_cdn_redirect_response("css/style.abc1234.css")
            assert response is not None
            assert response.status_code == 301
            assert response.headers["Cache-Control"] == "max-age=31536000, immutable"
            assert (
                response.headers["Location"]
                == "https://cdn.example.com/css/style.abc1234.css"
            )

    def test_non_fingerprinted_terminal_302_redirects(self):
        manifest = make_manifest()
        with override_settings(ASSETS_CDN_URL="https://cdn.example.com/"):
            view = make_asset_view(manifest, "js/app.js")
            response = view.get_cdn_redirect_response("js/app.js")
            assert response is not None
            assert response.status_code == 302
            assert response.headers["Cache-Control"] == "max-age=60"
            assert response.headers["Location"] == "https://cdn.example.com/js/app.js"

    def test_cdn_url_without_trailing_slash(self):
        """CDN URL works correctly with or without trailing slash."""
        manifest = make_manifest()
        with override_settings(
            ASSETS_CDN_URL="https://cdn.example.com"
        ):  # No trailing slash
            view = make_asset_view(manifest, "css/style.css")
            response = view.get_cdn_redirect_response("css/style.css")
            assert response is not None
            assert (
                response.headers["Location"]
                == "https://cdn.example.com/css/style.abc1234.css"
            )


class TestAssetViewLocalRedirect:
    """Tests for AssetView.get_redirect_response()

    Note: We only test the None cases because the redirect case calls reverse()
    which requires URL routing setup. The redirect logic is covered by CDN tests.
    """

    def test_terminal_path_returns_none(self):
        manifest = make_manifest()
        view = make_asset_view(manifest, "css/style.abc1234.css")
        assert view.get_redirect_response("css/style.abc1234.css") is None

    def test_unknown_path_returns_none(self):
        manifest = make_manifest()
        view = make_asset_view(manifest, "unknown.css")
        assert view.get_redirect_response("unknown.css") is None
