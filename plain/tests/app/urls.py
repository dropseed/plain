from plain.http import Response
from plain.urls import Router, path
from plain.views import View


class TestView(View):
    def get(self):
        return Response("Hello, world!")


class AppRouter(Router):
    namespace = ""
    urls = [
        path("", TestView, name="index"),
    ]
