from bolt.urls import include, path

from .views.default import AdminIndexView, AdminSearchView
from .views.registry import registry

default_namespace = "admin"


urlpatterns = [
    path("search/", AdminSearchView.as_view(), name="search"),
    path("", include(registry.get_urls())),
    path("", AdminIndexView.as_view(), name="index"),
]
