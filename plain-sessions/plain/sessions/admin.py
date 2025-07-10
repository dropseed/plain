from plain.admin.toolbar import ToolbarPanel, register_toolbar_panel
from plain.admin.views import (
    AdminModelDetailView,
    AdminModelListView,
    AdminViewset,
    register_viewset,
)

from .models import Session


@register_toolbar_panel
class SessionToolbarPanel(ToolbarPanel):
    name = "Session"
    template_name = "toolbar/session.html"


@register_viewset
class SessionAdmin(AdminViewset):
    class ListView(AdminModelListView):
        model = Session
        fields = ["session_key", "expires_at", "created_at"]
        search_fields = ["session_key"]
        nav_section = "Sessions"
        queryset_order = ["-created_at"]

    class DetailView(AdminModelDetailView):
        model = Session
