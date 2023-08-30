from bolt.urls import path
from . import views

app_name = "querystats"

urlpatterns = [
    path("", views.QuerystatsView.as_view(), name="querystats"),
]
