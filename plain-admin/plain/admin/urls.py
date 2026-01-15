from plain.urls import Router, include, path

from .builtin_views import (
    AdminIndexView,
    AdminSearchView,
    PinNavView,
    ReorderPinnedView,
    StyleGuideView,
    UnpinNavView,
)
from .impersonate.urls import ImpersonateRouter
from .views.registry import registry


class AdminRouter(Router):
    namespace = "admin"
    urls = [
        path("search/", AdminSearchView, name="search"),
        path("style/", StyleGuideView, name="style"),
        path("_/pin/", PinNavView, name="pin"),
        path("_/unpin/", UnpinNavView, name="unpin"),
        path("_/reorder/", ReorderPinnedView, name="reorder"),
        include("impersonate/", ImpersonateRouter),
        include("", registry.get_urls()),
        path("", AdminIndexView, name="index"),
    ]
