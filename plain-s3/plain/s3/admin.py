from __future__ import annotations

from plain.admin.views import (
    AdminModelDetailView,
    AdminModelListView,
    AdminViewset,
    register_viewset,
)

from .models import S3File


@register_viewset
class S3FileViewset(AdminViewset):
    class ListView(AdminModelListView):
        nav_section = "S3"
        model = S3File
        title = "Files"
        fields = [
            "id",
            "filename",
            "content_type",
            "size_display",
            "created_at",
        ]
        search_fields = [
            "filename",
            "key",
        ]
        queryset_order = ["-created_at"]
        actions = ["Delete"]

        def perform_action(self, action: str, target_ids: list) -> None:
            if action == "Delete":
                for file in S3File.query.filter(id__in=target_ids):
                    file.delete()  # This also deletes from S3

    class DetailView(AdminModelDetailView):
        model = S3File
        title = "File"
