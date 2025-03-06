from plain.urls import Router, path

from . import views


class LoginlinkRouter(Router):
    namespace = "loginlink"
    urls = [
        path("sent/", views.LoginLinkSentView.as_view(), name="sent"),
        path("failed/", views.LoginLinkFailedView.as_view(), name="failed"),
        path("token/<str:token>/", views.LoginLinkLoginView.as_view(), name="login"),
    ]
