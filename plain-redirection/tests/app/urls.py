from plain.http import Response
from plain.urls import Router, path
from plain.views import View


class HomeView(View):
    def get(self):
        return Response("home")


class AppRouter(Router):
    namespace = ""
    urls = [
        path("", HomeView, name="home"),
    ]
