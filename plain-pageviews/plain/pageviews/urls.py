from plain.urls import Router, path

from . import views


class PageviewsRouter(Router):
    namespace = "pageviews"
    urls = [
        path("track/", views.TrackView, name="track"),
    ]
