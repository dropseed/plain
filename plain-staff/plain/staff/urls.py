from plain.urls import include, path

from .impersonate import urls as impersonate_urls
from .querystats import urls as querystats_urls
from .views.default import StaffIndexView, StaffSearchView
from .views.registry import registry

default_namespace = "staff"


urlpatterns = [
    path("search/", StaffSearchView, name="search"),
    path("impersonate/", include(impersonate_urls)),
    path("querystats/", include(querystats_urls)),
    path("", include(registry.get_urls())),
    path("", StaffIndexView, name="index"),
]
