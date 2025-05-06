from plain.urls import Router, path
from plain.views import View


class ExampleView(View):
    def get(self):
        return {}


class AppRouter(Router):
    namespace = ""
    urls = [
        path("", ExampleView),
    ]
