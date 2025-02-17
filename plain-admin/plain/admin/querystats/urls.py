from plain.urls import RouterBase, path, register_router

from . import views


@register_router
class Router(RouterBase):
    namespace = "querystats"
    urls = [
        path("", views.QuerystatsView, name="querystats"),
    ]
