from plain.paginator import Paginator
from plain.utils import timezone


def url(viewname, *args, **kwargs):
    # A modified reverse that lets you pass args directly, excluding urlconf
    from plain.urls import reverse

    return reverse(viewname, args=args, kwargs=kwargs)


def asset(url_path):
    # An explicit callable we can control, but also delay the import of asset.urls->views->templates
    # for circular import reasons
    from plain.assets.urls import get_asset_url

    return get_asset_url(url_path)


default_globals = {
    "asset": asset,
    "url": url,
    "Paginator": Paginator,
    "now": timezone.now,
    "localtime": timezone.localtime,
}
