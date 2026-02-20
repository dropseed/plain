from plain.admin.views import (
    AdminModelDetailView,
    AdminModelListView,
    AdminViewset,
    register_viewset,
)

from .models import APIKey, DeviceGrant


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


@register_viewset
class DeviceGrantViewset(AdminViewset):
    class ListView(AdminModelListView):
        nav_section = "API"
        nav_icon = "smartphone"
        model = DeviceGrant
        title = "Device grants"
        description = "Pending and completed device authorization grants."
        fields = [
            "user_code",
            "status",
            "scope",
            "created_at__date",
            "expires_at__date",
        ]
        search_fields = ["user_code", "device_code"]

    class DetailView(AdminModelDetailView):
        model = DeviceGrant
        title = "Device grant"
