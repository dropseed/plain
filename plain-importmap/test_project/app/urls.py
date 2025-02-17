from plain.urls import RouterBase, path, register_router
from plain.views import TemplateView


@register_router
class Router(RouterBase):
    urls = [
        path("", TemplateView.as_view(template_name="index.html"), name="index"),
    ]
