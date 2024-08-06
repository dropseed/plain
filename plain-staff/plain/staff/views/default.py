from plain.http import ResponseRedirect

from .base import StaffView
from .registry import registry


# This will be dashboard view...
class StaffIndexView(StaffView):
    template_name = "staff/index.html"
    title = "Dashboards"
    slug = ""

    def get(self):
        # If there's exactly one dashboard, redirect straight to it
        dashboards = registry.registered_dashboards
        if len(dashboards) == 1:
            return ResponseRedirect(list(dashboards)[0].get_absolute_url())

        return super().get()

    def get_template_context(self):
        context = super().get_template_context()
        context["dashboards"] = registry.registered_dashboards
        return context


class StaffSearchView(StaffView):
    template_name = "staff/search.html"
    title = "Search"
    slug = "search"

    def get_template_context(self):
        context = super().get_template_context()
        context["searchable_views"] = registry.get_searchable_views()
        context["global_search_query"] = self.request.GET.get("query", "")
        return context
