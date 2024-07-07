from plain.urls import include, path

from . import views

default_namespace = "oauth"

urlpatterns = [
    path(
        "<str:provider>/",
        include(
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
            ]
        ),
    ),
]
