from plain.cache.models import CachedItem
from plain.staff.views import (
    StaffModelDetailView,
    StaffModelListView,
    StaffModelViewset,
    register_viewset,
)


@register_viewset
class CachedItemViewset(StaffModelViewset):
    class ListView(StaffModelListView):
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

    class DetailView(StaffModelDetailView):
        model = CachedItem
        title = "Cached item"
