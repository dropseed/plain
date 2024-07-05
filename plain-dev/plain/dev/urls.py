from plain.urls import path

from . import views

default_namespace = "dev"

urlpatterns = [
    path("", views.RequestsView, name="requests"),
]
