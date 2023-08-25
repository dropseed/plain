from bolt.urls import path
from .views import RequestLogView

app_name = "requestlog"

urlpatterns = [
    path("", RequestLogView.as_view(), name="list"),
]
