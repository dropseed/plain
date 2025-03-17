from plain.runtime import settings
from plain.urls import Router, path, reverse

from .fingerprints import get_fingerprinted_url_path
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


def get_asset_url(url_path):
    """
    Get the full URL to a given asset path.
    """
    if settings.DEBUG:
        # In debug, we only ever use the original URL path.
        resolved_url_path = url_path
    else:
        # If a fingerprinted URL path is available, use that.
        if fingerprinted_url_path := get_fingerprinted_url_path(url_path):
            resolved_url_path = fingerprinted_url_path
        else:
            resolved_url_path = url_path

    # If a base url is set (i.e. a CDN),
    # then do a simple join to get the full URL.
    if settings.ASSETS_BASE_URL:
        return settings.ASSETS_BASE_URL + resolved_url_path

    return reverse(AssetsRouter.namespace + ":asset", path=resolved_url_path)
