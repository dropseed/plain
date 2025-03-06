from plain.urls import Router, path

from . import views


class QuerystatsRouter(Router):
    namespace = "querystats"
    urls = [
        path("", views.QuerystatsView, name="querystats"),
    ]
