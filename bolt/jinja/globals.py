from bolt.paginator import Paginator
from bolt.staticfiles.storage import staticfiles_storage


def url(viewname, *args, **kwargs):
    # A modified reverse that lets you pass args directly, excluding urlconf
    from bolt.urls import reverse

    return reverse(viewname, args=args, kwargs=kwargs)


def static(path):
    return staticfiles_storage.url(path)


default_globals = {
    "static": static,
    "url": url,
    "Paginator": Paginator,
}
