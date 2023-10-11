from bolt.urls import path

from . import views

default_namespace = "dev"

urlpatterns = [
    path("", views.RequestsView.as_view(), name="requests"),
]
