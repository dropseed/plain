from plain.urls import RouterBase, register_router

from .registry import registry


@register_router
class Router(RouterBase):
    namespace = "pages"
    urls = registry.get_page_urls()
