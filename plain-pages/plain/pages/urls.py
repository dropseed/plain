from plain.urls import Router

from .registry import registry


class PagesRouter(Router):
    namespace = "pages"
    urls = registry.get_page_urls()
