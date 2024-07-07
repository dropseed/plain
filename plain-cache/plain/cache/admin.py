from plain.cache.models import CachedItem
from plain.staff.admin.views import (
    AdminModelDetailView,
    AdminModelListView,
    AdminModelViewset,
    register_viewset,
)


@register_viewset
class CachedItemViewset(AdminModelViewset):
    class ListView(AdminModelListView):
        nav_section = "Cache"
        model = CachedItem
        title = "Cached items"
        fields = [
            "key",
            "created_at",
            "expires_at",
            "updated_at",
        ]
        queryset_order = ["-pk"]
        allow_global_search = False

        def get_list_queryset(self):
            return CachedItem.objects.all().only(
                "key", "created_at", "expires_at", "updated_at"
            )

    class DetailView(AdminModelDetailView):
        model = CachedItem
        title = "Cached item"
