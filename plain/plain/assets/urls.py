from plain.runtime import settings
from plain.urls import path, reverse

from .fingerprints import get_fingerprinted_url_path
from .views import AssetView

default_namespace = "assets"


def get_asset_url(url_path):
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

    return reverse(default_namespace + ":asset", kwargs={"path": resolved_url_path})


urlpatterns = [
    path("<path:path>", AssetView, name="asset"),
]
