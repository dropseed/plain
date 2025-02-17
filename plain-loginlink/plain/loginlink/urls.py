from plain.urls import RouterBase, path, register_router

from . import views


@register_router
class Router(RouterBase):
    namespace = "loginlink"
    urls = [
        path("sent/", views.LoginLinkSentView.as_view(), name="sent"),
        path("failed/", views.LoginLinkFailedView.as_view(), name="failed"),
        path("token/<str:token>/", views.LoginLinkLoginView.as_view(), name="login"),
    ]
