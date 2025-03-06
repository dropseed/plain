from plain.urls import Router, include, path

from . import views


class OAuthRouter(Router):
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
