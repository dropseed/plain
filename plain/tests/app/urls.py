from plain.urls import Router, path
from plain.views import View


class TestView(View):
    def get(self):
        return "Hello, world!"


class AppRouter(Router):
    namespace = ""
    urls = [
        path("", TestView),
    ]
