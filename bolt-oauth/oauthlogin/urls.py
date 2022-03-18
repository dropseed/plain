from django.urls import include, path

from . import views

app_name = "oauthlogin"

urlpatterns = [
    path(
        "<str:provider>/",
        include(
            [
                # Login and Signup are both handled here, because the intent is the same
                path("login/", views.OAuthLoginView.as_view(), name="login"),
                path("connect/", views.OAuthConnectView.as_view(), name="connect"),
                path(
                    "disconnect/",
                    views.OAuthDisconnectView.as_view(),
                    name="disconnect",
                ),
                path("callback/", views.OAuthCallbackView.as_view(), name="callback"),
            ]
        ),
    ),
]
