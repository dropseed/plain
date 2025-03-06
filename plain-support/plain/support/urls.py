from plain.urls import Router, path

from . import views


class SupportRouter(Router):
    namespace = "support"
    urls = [
        path("form/<slug:form_slug>.js", views.SupportFormJSView),
        path("form/<slug:form_slug>/iframe/", views.SupportIFrameView, name="iframe"),
        path("form/<slug:form_slug>/", views.SupportFormView, name="form"),
    ]
