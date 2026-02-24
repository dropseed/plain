from datetime import timedelta

from plain.paginator import Paginator
from plain.urls import absolute_url, reverse, reverse_absolute
from plain.utils import timezone


def _asset(url_path: str) -> str:
    # An explicit callable we can control, but also delay the import of asset.urls->views->templates
    # for circular import reasons
    from plain.assets.urls import get_asset_url

    return get_asset_url(url_path)


default_globals = {
    "asset": _asset,
    "url": reverse,  # Alias for reverse
    "reverse": reverse,
    "reverse_absolute": reverse_absolute,
    "absolute_url": absolute_url,
    "Paginator": Paginator,
    "now": timezone.now,
    "timedelta": timedelta,
    "localtime": timezone.localtime,
}
