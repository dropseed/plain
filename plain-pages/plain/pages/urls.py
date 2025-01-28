from plain.urls import include, path

from .registry import registry

default_namespace = "pages"


urlpatterns = [
    path("", include(registry.get_page_urls())),
]
