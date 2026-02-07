from plain.admin.views import (
    AdminModelDetailView,
    AdminModelListView,
    AdminViewset,
    register_viewset,
)

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
        queryset_order = ["-created_at"]

    class DetailView(AdminModelDetailView):
        model = User
