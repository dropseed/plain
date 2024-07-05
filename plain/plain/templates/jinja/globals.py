from plain.assets import get_asset_url
from plain.paginator import Paginator
from plain.utils import timezone


def url(viewname, *args, **kwargs):
    # A modified reverse that lets you pass args directly, excluding urlconf
    from plain.urls import reverse

    return reverse(viewname, args=args, kwargs=kwargs)


default_globals = {
    "asset": get_asset_url,
    "url": url,
    "Paginator": Paginator,
    "now": timezone.now,
    "localtime": timezone.localtime,
}
