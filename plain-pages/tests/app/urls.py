from plain.pages.urls import PagesRouter
from plain.urls import Router, include


class AppRouter(Router):
    namespace = ""
    urls = [
        include("", PagesRouter),
    ]
