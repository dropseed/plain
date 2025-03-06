from plain.urls import Router, path

from . import views


class DevRequestsRouter(Router):
    namespace = "dev"
    urls = [
        path("", views.RequestsView, name="requests"),
    ]
