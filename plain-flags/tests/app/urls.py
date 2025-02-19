from plain.urls import RouterBase, register_router


@register_router
class Router(RouterBase):
    namespace = ""
    urls = []
