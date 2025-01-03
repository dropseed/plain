from plain.urls import path

from . import views

default_namespace = "pageviews"

urlpatterns = [
    path("track/", views.TrackView, name="track"),
]
