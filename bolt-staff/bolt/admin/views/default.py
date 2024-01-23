from bolt.http import HttpResponseRedirect

from .base import AdminView
from .registry import registry


# This will be dashboard view...
class AdminIndexView(AdminView):
    template_name = "admin/index.html"
    title = "Admin"
    slug = ""

    def get(self):
        # If there's exactly one dashboard, redirect straight to it
        dashboards = registry.registered_dashboards
        if len(dashboards) == 1:
            return HttpResponseRedirect(list(dashboards)[0].get_absolute_url())

        return super().get()

    def get_template_context(self):
        context = super().get_template_context()
        context["dashboards"] = registry.registered_dashboards
        return context


class AdminSearchView(AdminView):
    template_name = "admin/search.html"
    title = "Search"
    slug = "search"

    def get_template_context(self):
        context = super().get_template_context()
        context["searchable_views"] = registry.get_searchable_views()
        context["global_search_query"] = self.request.GET.get("query", "")
        return context
