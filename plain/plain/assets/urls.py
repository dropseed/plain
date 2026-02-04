from plain.runtime import settings
from plain.urls import Router, path, reverse

from .manifest import get_manifest
from .views import AssetView


class AssetsRouter(Router):
    """
    The router for serving static assets.

    Include this router in your app router if you are serving assets yourself.
    """

    namespace = "assets"
    urls = [
        path("<path:path>", AssetView, name="asset"),
    ]


def get_asset_url(url_path: str) -> str:
    """Get the full URL to a given asset path."""
    # In debug mode, always use the original URL path.
    # In production, use compiled URL path if available (may be fingerprinted).
    if settings.DEBUG:
        resolved_url_path = url_path
    else:
        resolved_url_path = get_manifest().resolve(url_path) or url_path

    if settings.ASSETS_CDN_URL:
        return f"{settings.ASSETS_CDN_URL.rstrip('/')}/{resolved_url_path.lstrip('/')}"

    return reverse(f"{AssetsRouter.namespace}:asset", path=resolved_url_path)
