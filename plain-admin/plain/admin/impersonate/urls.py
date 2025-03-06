from plain.urls import Router, path

from .views import ImpersonateStartView, ImpersonateStopView


class ImpersonateRouter(Router):
    namespace = "impersonate"
    urls = [
        path("stop/", ImpersonateStopView, name="stop"),
        path("start/<pk>/", ImpersonateStartView, name="start"),
    ]
