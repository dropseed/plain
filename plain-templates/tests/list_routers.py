"""Views and routers for test_list_view.py."""

from __future__ import annotations

from plain.templates.views import ListView
from plain.urls import Router, path

ITEMS = [f"item-{i}" for i in range(1, 8)]  # 7 items


class UnpaginatedListView(ListView):
    template_name = "items.html"

    def get_objects(self) -> list[str]:
        return ITEMS


class PaginatedListView(ListView):
    template_name = "items.html"
    page_size = 3

    def get_objects(self) -> list[str]:
        return ITEMS


class EmptyPaginatedListView(ListView):
    template_name = "items.html"
    page_size = 3

    def get_objects(self) -> list[str]:
        return []


class ListRouter(Router):
    namespace = ""
    urls = [
        path("unpaginated", UnpaginatedListView),
        path("paginated", PaginatedListView),
        path("empty", EmptyPaginatedListView),
    ]
