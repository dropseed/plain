from plain.urls import Router

from .registry import pages_registry


class PagesRouter(Router):
    namespace = "pages"
    urls = pages_registry.get_page_urls()
