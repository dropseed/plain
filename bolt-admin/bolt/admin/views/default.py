from bolt.http import HttpResponseRedirect

from .base import AdminPageView
from .registry import registry


# This will be dashboard view...
class AdminIndexView(AdminPageView):
    template_name = "admin/index.html"
    title = "Admin"
    slug = ""

    def get(self):
        # If there's exactly one dashboard, redirect straight to it
        dashboards = registry.registered_dashboards
        if len(dashboards) == 1:
            return HttpResponseRedirect(list(dashboards)[0].get_absolute_url())

        return super().get()

    def get_context(self):
        context = super().get_context()
        context["dashboards"] = registry.registered_dashboards
        return context
