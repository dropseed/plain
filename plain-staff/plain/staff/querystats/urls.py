from plain.urls import path

from . import views

default_namespace = "querystats"

urlpatterns = [
    path("", views.QuerystatsView, name="querystats"),
]
