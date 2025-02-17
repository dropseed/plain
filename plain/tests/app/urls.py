from plain.urls import RouterBase, path, register_router
from plain.views import View


class TestView(View):
    def get(self):
        return "Hello, world!"


@register_router
class Router(RouterBase):
    urls = [
        path("", TestView),
    ]
