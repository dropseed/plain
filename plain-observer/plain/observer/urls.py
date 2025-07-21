from plain.urls import Router, path

from . import views


class ObserverRouter(Router):
    namespace = "observer"
    urls = [
        path("traces/", views.ObserverTracesView, name="traces"),
        path("traces/<trace_id>/", views.ObserverTraceDetailView, name="trace_detail"),
        path("share/<share_id>/", views.ObserverTraceSharedView, name="trace_shared"),
    ]
