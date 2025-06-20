from plain.urls import Router, path

from . import views


class ObserveRouter(Router):
    namespace = "observe"
    urls = [
        path("", views.ObservabilitySpansView, name="spans"),
    ]
