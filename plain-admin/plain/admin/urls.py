from plain.http import ResponseRedirect
from plain.urls import Router, include, path

from .impersonate.urls import ImpersonateRouter
from .querystats.urls import QuerystatsRouter
from .views.base import AdminView
from .views.registry import registry


class AdminIndexView(AdminView):
    template_name = "admin/index.html"
    title = "Dashboard"

    def get(self):
        # Slight hack to redirect to the first view that doesn't
        # require any url params...
        if views := registry.get_searchable_views():
            return ResponseRedirect(list(views)[0].get_view_url())

        return super().get()


class AdminSearchView(AdminView):
    template_name = "admin/search.html"
    title = "Search"

    def get_template_context(self):
        context = super().get_template_context()
        context["searchable_views"] = registry.get_searchable_views()
        context["global_search_query"] = self.request.query_params.get("query", "")
        return context


class AdminRouter(Router):
    namespace = "admin"
    urls = [
        path("search/", AdminSearchView, name="search"),
        include("impersonate/", ImpersonateRouter),
        include("querystats/", QuerystatsRouter),
        include("", registry.get_urls()),
        path("", AdminIndexView, name="index"),
    ]
