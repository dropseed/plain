from bolt.urls import path

from . import views

default_namespace = "querystats"

urlpatterns = [
    path("", views.QuerystatsView.as_view(), name="querystats"),
]
