from plain.admin.views import (
    AdminModelDetailView,
    AdminModelListView,
    AdminViewset,
    register_viewset,
)

from .models import APIKey


@register_viewset
class APIKeyViewset(AdminViewset):
    class ListView(AdminModelListView):
        nav_section = "API"
        nav_icon = "key"
        model = APIKey
        title = "API keys"
        description = "Keys used to authenticate API requests."
        fields = [
            "name",
            "uuid",
            "api_version",
            "created_at__date",
            "last_used_at__date",
            "expires_at__date",
        ]
        search_fields = ["name", "uuid"]

    class DetailView(AdminModelDetailView):
        model = APIKey
        title = "API key"
