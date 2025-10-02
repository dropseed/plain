from __future__ import annotations

from plain.admin.views import (
    AdminModelDetailView,
    AdminModelListView,
    AdminViewset,
    register_viewset,
)
from plain.cache.models import CachedItem
from plain.models import QuerySet


@register_viewset
class CachedItemViewset(AdminViewset):
    class ListView(AdminModelListView):
        nav_section = "Cache"
        nav_icon = "archive"
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

        def get_objects(self) -> QuerySet[CachedItem]:
            return (
                super()
                .get_objects()
                .only("key", "created_at", "expires_at", "updated_at")
            )

    class DetailView(AdminModelDetailView):
        model = CachedItem
        title = "Cached item"
