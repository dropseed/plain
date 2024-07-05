from plain.urls import include, path

from .views.default import AdminIndexView, AdminSearchView
from .views.registry import registry

default_namespace = "admin"


urlpatterns = [
    path("search/", AdminSearchView, name="search"),
    path("", include(registry.get_urls())),
    path("", AdminIndexView, name="index"),
]
