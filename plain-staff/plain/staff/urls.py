from plain.http import ResponseRedirect
from plain.urls import include, path

from .impersonate import urls as impersonate_urls
from .querystats import urls as querystats_urls
from .views.base import StaffView
from .views.registry import registry


class StaffIndexView(StaffView):
    template_name = "staff/index.html"
    title = "Dashboard"
    slug = ""

    def get(self):
        # Slight hack to redirect to the first view that doesn't
        # require any url params...
        if views := registry.get_searchable_views():
            return ResponseRedirect(list(views)[0].get_absolute_url())

        return super().get()


class StaffSearchView(StaffView):
    template_name = "staff/search.html"
    title = "Search"
    slug = "search"

    def get_template_context(self):
        context = super().get_template_context()
        context["searchable_views"] = registry.get_searchable_views()
        context["global_search_query"] = self.request.GET.get("query", "")
        return context


default_namespace = "staff"


urlpatterns = [
    path("search/", StaffSearchView, name="search"),
    path("impersonate/", include(impersonate_urls)),
    path("querystats/", include(querystats_urls)),
    path("", include(registry.get_urls())),
    path("", StaffIndexView, name="index"),
]
