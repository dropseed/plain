from bolt.assets.storage import assets_storage
from bolt.paginator import Paginator


def url(viewname, *args, **kwargs):
    # A modified reverse that lets you pass args directly, excluding urlconf
    from bolt.urls import reverse

    return reverse(viewname, args=args, kwargs=kwargs)


def asset(path):
    return assets_storage.url(path)


default_globals = {
    "asset": asset,
    "url": url,
    "Paginator": Paginator,
}
