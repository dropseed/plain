from plain.admin.views import (
    AdminModelDetailView,
    AdminModelListView,
    AdminViewset,
    register_viewset,
)

from .models import Session


@register_viewset
class SessionAdmin(AdminViewset):
    class ListView(AdminModelListView):
        model = Session
        fields = ["id", "expires_at", "created_at"]
        search_fields = ["session_key"]
        nav_section = "Sessions"
        nav_icon = "person-badge"
        queryset_order = ["-created_at"]

    class DetailView(AdminModelDetailView):
        model = Session
