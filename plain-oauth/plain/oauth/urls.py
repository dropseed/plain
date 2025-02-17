from plain.urls import RouterBase, include, path, register_router

from . import views


@register_router
class Router(RouterBase):
    namespace = "oauth"
    urls = [
        include(
            "<str:provider>/",
            [
                # Login and Signup are both handled here, because the intent is the same
                path("login/", views.OAuthLoginView, name="login"),
                path("connect/", views.OAuthConnectView, name="connect"),
                path(
                    "disconnect/",
                    views.OAuthDisconnectView,
                    name="disconnect",
                ),
                path("callback/", views.OAuthCallbackView, name="callback"),
            ],
        ),
    ]
