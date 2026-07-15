from plain import postgres
from plain.admin.views import (
    AdminModelDetailView,
    AdminModelListView,
    AdminViewset,
    register_viewset,
)
from plain.http import Response

from .models import User


@register_viewset
class UserAdmin(AdminViewset):
    class ListView(AdminModelListView):
        model = User
        nav_section = "Users"
        nav_icon = "person"
        title = "Users"
        fields = ["id", "email", "is_admin", "created_at"]
        search_fields = ["email"]
        actions = ["Make admin", "Remove admin", "Export emails"]
        allow_global_search = True
        queryset_order = ["-created_at"]

        def perform_action(
            self, action: str, objects: postgres.QuerySet
        ) -> Response | None:
            if action == "Make admin":
                objects.update(is_admin=True)
            elif action == "Remove admin":
                objects.update(is_admin=False)
            elif action == "Export emails":
                emails = objects.values_list("email", flat=True)
                return Response("\n".join(emails), content_type="text/plain")
            return None

    class DetailView(AdminModelDetailView):
        model = User
