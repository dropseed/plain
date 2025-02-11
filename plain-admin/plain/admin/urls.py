from plain.http import ResponseRedirect
from plain.urls import include, path

from .impersonate import urls as impersonate_urls
from .querystats import urls as querystats_urls
from .views.base import AdminView
from .views.registry import registry


class AdminIndexView(AdminView):
    template_name = "admin/index.html"
    title = "Dashboard"
    slug = ""

    def get(self):
        # Slight hack to redirect to the first view that doesn't
        # require any url params...
        if views := registry.get_searchable_views():
            return ResponseRedirect(list(views)[0].get_view_url())

        return super().get()


class AdminSearchView(AdminView):
    template_name = "admin/search.html"
    title = "Search"
    slug = "search"

    def get_template_context(self):
        context = super().get_template_context()
        context["searchable_views"] = registry.get_searchable_views()
        context["global_search_query"] = self.request.GET.get("query", "")
        return context


default_namespace = "admin"


urlpatterns = [
    path("search/", AdminSearchView, name="search"),
    path("impersonate/", include(impersonate_urls)),
    path("querystats/", include(querystats_urls)),
    path("", include(registry.get_urls())),
    path("", AdminIndexView, name="index"),
]
