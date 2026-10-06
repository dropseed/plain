from plain.assets.manifest import AssetsManifest
from plain.assets.views import AssetView
from plain.testing import build_request, override_settings


def make_asset_view(manifest: AssetsManifest, path: str) -> AssetView:
    """Create an AssetView with a test manifest."""

    class TestAssetView(AssetView):
        def get_manifest(self):
            return manifest

    request = build_request("GET", f"/assets/{path}")
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


# Assets manifest
#
# Tests for AssetsManifest class.
def test_manifest_is_immutable_true_for_fingerprinted_path():
    manifest = make_manifest()
    assert manifest.is_immutable("css/style.abc1234.css") is True


def test_manifest_is_immutable_false_for_original_path():
    manifest = make_manifest()
    assert manifest.is_immutable("css/style.css") is False


def test_manifest_is_immutable_false_for_unknown_path():
    manifest = make_manifest()
    assert manifest.is_immutable("unknown.css") is False


def test_manifest_is_immutable_false_for_non_fingerprinted_terminal():
    manifest = make_manifest()
    assert manifest.is_immutable("js/app.js") is False


def test_manifest_resolve_returns_fingerprinted_for_original():
    manifest = make_manifest()
    assert manifest.resolve("css/style.css") == "css/style.abc1234.css"


def test_manifest_resolve_returns_same_path_for_terminal():
    manifest = make_manifest()
    assert manifest.resolve("css/style.abc1234.css") == "css/style.abc1234.css"
    assert manifest.resolve("js/app.js") == "js/app.js"


def test_manifest_resolve_returns_none_for_unknown():
    manifest = make_manifest()
    assert manifest.resolve("unknown.css") is None


# Asset view CDN redirect
#
# Tests for AssetView.get_cdn_redirect_response()
def test_cdn_redirect_not_in_manifest_returns_none():
    manifest = make_manifest()
    view = make_asset_view(manifest, "unknown.css")
    assert view.get_cdn_redirect_response("unknown.css") is None


def test_cdn_redirect_original_path_302_redirects_to_fingerprinted():
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


def test_cdn_redirect_fingerprinted_terminal_301_redirects():
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


def test_cdn_redirect_non_fingerprinted_terminal_302_redirects():
    manifest = make_manifest()
    with override_settings(ASSETS_CDN_URL="https://cdn.example.com/"):
        view = make_asset_view(manifest, "js/app.js")
        response = view.get_cdn_redirect_response("js/app.js")
        assert response is not None
        assert response.status_code == 302
        assert response.headers["Cache-Control"] == "max-age=60"
        assert response.headers["Location"] == "https://cdn.example.com/js/app.js"


def test_cdn_redirect_cdn_url_without_trailing_slash():
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


# Asset view local redirect
#
# Tests for AssetView.get_redirect_response()
#
# Note: We only test the None cases because the redirect case calls reverse()
# which requires URL routing setup. The redirect logic is covered by CDN tests.
def test_local_redirect_terminal_path_returns_none():
    manifest = make_manifest()
    view = make_asset_view(manifest, "css/style.abc1234.css")
    assert view.get_redirect_response("css/style.abc1234.css") is None


def test_local_redirect_unknown_path_returns_none():
    manifest = make_manifest()
    view = make_asset_view(manifest, "unknown.css")
    assert view.get_redirect_response("unknown.css") is None
