from plain.urls import RouterBase, path, register_router

from . import views


@register_router
class Router(RouterBase):
    namespace = "dev"
    urls = [
        path("", views.RequestsView, name="requests"),
    ]
