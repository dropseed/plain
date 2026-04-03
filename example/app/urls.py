from __future__ import annotations

from typing import NoReturn

from app.views.sse import ClockView, StockTickerView
from plain.admin.urls import AdminRouter
from plain.assets.urls import AssetsRouter
from plain.auth.views import LogoutView
from plain.mcp import MCPRouter
from plain.observer.urls import ObserverRouter
from plain.passwords.views import PasswordLoginView
from plain.urls import Router, include, path
from plain.views import TemplateView


class LoginView(PasswordLoginView):
    template_name = "login.html"


class SSEDemoView(TemplateView):
    template_name = "sse.html"


class IndexView(TemplateView):
    template_name = "index.html"


class ErrorView(TemplateView):
    template_name = "index.html"

    def get(self) -> NoReturn:
        text = "This is a test exception to demonstrate the toolbar"
        raise ValueError(text)


class AppRouter(Router):
    namespace = ""
    urls = [
        include("admin/", AdminRouter),
        include("assets/", AssetsRouter),
        include("mcp/", MCPRouter),
        include("observer/", ObserverRouter),
        path("login/", LoginView, name="login"),
        path("logout/", LogoutView, name="logout"),
        path("error/", ErrorView, name="error"),
        path("sse/", SSEDemoView, name="sse_demo"),
        path("sse/clock/", ClockView, name="sse_clock"),
        path("sse/ticker/", StockTickerView, name="sse_ticker"),
        path("", IndexView, name="index"),
    ]
