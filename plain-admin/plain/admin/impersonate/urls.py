from plain.urls import RouterBase, path, register_router

from .views import ImpersonateStartView, ImpersonateStopView


@register_router
class Router(RouterBase):
    namespace = "impersonate"
    urls = [
        path("stop/", ImpersonateStopView, name="stop"),
        path("start/<pk>/", ImpersonateStartView, name="start"),
    ]
