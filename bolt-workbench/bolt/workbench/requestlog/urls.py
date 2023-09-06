from bolt.urls import path

from .views import RequestLogView

default_namespace = "requestlog"

urlpatterns = [
    path("", RequestLogView.as_view(), name="list"),
]
