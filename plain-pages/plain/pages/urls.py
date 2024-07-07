from plain.runtime import settings
from plain.urls import include, path
from plain.utils.module_loading import import_string

from .registry import registry

default_namespace = "pages"


def get_page_urls():
    """
    Generate a list of real urls based on the files that exist.
    This way, you get a concrete url reversingerror if you try
    to refer to a page/url that isn't going to work.
    """
    paths = []

    view_class = import_string(settings.PAGES_VIEW_CLASS)

    for url_path in registry.url_paths():
        if url_path == "":
            # The root index is a special case and should be
            # referred to as pages:index
            url = ""
            name = "index"
        else:
            url = url_path + "/"
            name = url_path

        paths.append(
            path(
                url,
                view_class,
                name=name,
                kwargs={"url_path": url_path},
            )
        )

    return paths


urlpatterns = [
    path("", include(get_page_urls())),
]
