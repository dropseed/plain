from django.urls import include, path

from .views.default import AdminIndexView
from .views.registry import registry

app_name = "boltadmin"


urlpatterns = [
    path("", include(registry.get_urls())),
    path("", AdminIndexView.as_view(), name="index"),
]
