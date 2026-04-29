from plain.auth.views import LogoutView
from plain.urls import Router, include, path

from .builtin_views import (
    AdminIndexView,
    AdminSearchView,
    ComponentsView,
    PinNavView,
    PreflightView,
    ReorderPinnedView,
    SettingDetailView,
    SettingsView,
    UnpinNavView,
)
from .impersonate.urls import ImpersonateRouter
from .views.registry import registry

__all__ = ["AdminRouter"]


class AdminRouter(Router):
    namespace = "admin"
    urls = [
        path("search/", AdminSearchView, name="search"),
        path("components/", ComponentsView, name="components"),
        path("settings/", SettingsView, name="settings"),
        path("settings/<name>/", SettingDetailView, name="setting_detail"),
        path("preflight/", PreflightView, name="preflight"),
        path("logout/", LogoutView, name="logout"),
        path("_/pin/", PinNavView, name="pin"),
        path("_/unpin/", UnpinNavView, name="unpin"),
        path("_/reorder/", ReorderPinnedView, name="reorder"),
        include("impersonate/", ImpersonateRouter),
        include("", registry.get_urls()),
        path("", AdminIndexView, name="index"),
    ]
