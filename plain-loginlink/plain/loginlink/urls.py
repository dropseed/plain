from plain.urls import Router, path

from . import views


class LoginlinkRouter(Router):
    namespace = "loginlink"
    urls = [
        path("sent/", views.LoginLinkSentView, name="sent"),
        path("failed/", views.LoginLinkFailedView, name="failed"),
        path("token/<str:token>/", views.LoginLinkLoginView, name="login"),
    ]
