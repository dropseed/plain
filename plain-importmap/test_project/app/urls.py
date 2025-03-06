from plain.urls import Router, path
from plain.views import TemplateView


class AppRouter(Router):
    namespace = ""
    urls = [
        path("", TemplateView.as_view(template_name="index.html"), name="index"),
    ]
