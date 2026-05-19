from plain.assets.urls import AssetsRouter
from plain.html.views import TemplateView
from plain.urls import Router, include, path


class PageView(TemplateView):
    template_name = "page.html"


class AppRouter(Router):
    namespace = ""
    urls = [
        include("assets", AssetsRouter),
        path("", PageView, name="page"),
    ]
