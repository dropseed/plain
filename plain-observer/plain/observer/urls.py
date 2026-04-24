from plain.urls import Router, path

from . import views


class ObserverRouter(Router):
    namespace = "observer"
    urls = [
        path("", views.ObserverIndexView, name="index"),
        path("traces/", views.ObserverTracesView, name="traces"),
        path("traces/<trace_id>/", views.ObserverTraceDetailView, name="trace_detail"),
    ]
