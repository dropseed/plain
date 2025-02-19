from datetime import timedelta

from plain.paginator import Paginator
from plain.urls import reverse
from plain.utils import timezone


def asset(url_path):
    # An explicit callable we can control, but also delay the import of asset.urls->views->templates
    # for circular import reasons
    from plain.assets.urls import get_asset_url

    return get_asset_url(url_path)


default_globals = {
    "asset": asset,
    "url": reverse,
    "Paginator": Paginator,
    "now": timezone.now,
    "timedelta": timedelta,
    "localtime": timezone.localtime,
}
