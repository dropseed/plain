from plain.admin.views import (
    AdminModelDetailView,
    AdminModelListView,
    AdminViewset,
    register_viewset,
)
from plain.cache.models import CachedItem


@register_viewset
class CachedItemViewset(AdminViewset):
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
        queryset_order = ["-id"]
        allow_global_search = False

        def get_objects(self):
            return (
                super()
                .get_objects()
                .only("key", "created_at", "expires_at", "updated_at")
            )

    class DetailView(AdminModelDetailView):
        model = CachedItem
        title = "Cached item"
