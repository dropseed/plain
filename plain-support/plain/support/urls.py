from plain.urls import RouterBase, path, register_router

from . import views


@register_router
class Router(RouterBase):
    namespace = "support"
    urls = [
        path("form/<slug:form_slug>.js", views.SupportFormJSView),
        path("form/<slug:form_slug>/iframe/", views.SupportIFrameView, name="iframe"),
        path("form/<slug:form_slug>/", views.SupportFormView, name="form"),
    ]
