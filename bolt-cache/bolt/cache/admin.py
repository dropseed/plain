from bolt.admin import (
    AdminModelDetailView,
    AdminModelListView,
    AdminModelViewset,
    register_viewset,
)
from bolt.cache.models import CachedItem


@register_viewset
class CachedItemViewset(AdminModelViewset):
    class ListView(AdminModelListView):
        nav_section = "Cache"
        model = CachedItem
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