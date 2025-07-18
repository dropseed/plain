from plain.urls import Router, path

from . import views


class ObserverRouter(Router):
    namespace = "observer"
    urls = [
        path("", views.ObserverTracesView, name="traces"),
    ]
