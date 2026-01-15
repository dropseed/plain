"""Built-in admin views for core functionality."""

import json
from typing import Any

from plain.http import RedirectResponse, Response

from .models import PinnedNavItem
from .views.base import AdminView
from .views.registry import registry

MAX_PINNED_ITEMS = 6


class AdminIndexView(AdminView):
    template_name = "admin/index.html"
    title = "Dashboard"

    def get(self) -> Response:
        # Slight hack to redirect to the first view that doesn't
        # require any url params...
        if views := registry.get_searchable_views():
            return RedirectResponse(list(views)[0].get_view_url())

        return super().get()


class AdminSearchView(AdminView):
    template_name = "admin/search.html"
    title = "Search"

    def get_template_context(self) -> dict[str, Any]:
        context = super().get_template_context()
        context["searchable_views"] = registry.get_searchable_views()
        context["global_search_query"] = self.request.query_params.get("query", "")
        return context


class PinNavView(AdminView):
    """Pin a navigation item for the current user."""

    nav_section = None

    def post(self) -> Response:
        view_slug = self.request.form_data.get("view_slug")
        if not view_slug:
            return Response("view_slug is required", status_code=400)

        # Check if user has reached max pinned items
        current_count = PinnedNavItem.query.filter(user=self.user).count()
        if current_count >= MAX_PINNED_ITEMS:
            return Response(
                f"Maximum of {MAX_PINNED_ITEMS} pinned items reached",
                status_code=400,
            )

        # Verify the view slug exists
        if not registry.get_view_by_slug(view_slug):
            return Response("Invalid view_slug", status_code=400)

        max_order = (
            PinnedNavItem.query.filter(user=self.user)
            .order_by("-order")
            .values_list("order", flat=True)
            .first()
        )
        next_order = (max_order or 0) + 1

        PinnedNavItem.query.get_or_create(
            user=self.user,
            view_slug=view_slug,
            defaults={"order": next_order},
        )

        # Redirect back to current page (or referer)
        referer = self.request.headers.get("Referer", "/admin/")
        return RedirectResponse(referer)


class UnpinNavView(AdminView):
    """Unpin a navigation item for the current user."""

    nav_section = None

    def post(self) -> Response:
        view_slug = self.request.form_data.get("view_slug")
        if not view_slug:
            return Response("view_slug is required", status_code=400)

        PinnedNavItem.query.filter(
            user=self.user,
            view_slug=view_slug,
        ).delete()

        # Redirect back to current page (or referer)
        referer = self.request.headers.get("Referer", "/admin/")
        return RedirectResponse(referer)


class ReorderPinnedView(AdminView):
    """Reorder pinned navigation items."""

    nav_section = None

    def post(self) -> Response:
        slugs_json = self.request.form_data.get("slugs")
        if not slugs_json:
            return Response("slugs is required", status_code=400)

        try:
            slugs = json.loads(slugs_json)
        except json.JSONDecodeError:
            return Response("Invalid slugs JSON", status_code=400)

        # Only update slugs that exist and belong to this user
        user_pinned = set(
            PinnedNavItem.query.filter(user=self.user).values_list(
                "view_slug", flat=True
            )
        )
        for i, slug in enumerate(slugs):
            if slug in user_pinned:
                PinnedNavItem.query.filter(user=self.user, view_slug=slug).update(
                    order=i
                )

        # No redirect needed for drag-and-drop reorder (called via fetch)
        return Response("OK")


class StyleGuideView(AdminView):
    """Style guide showing available components and patterns."""

    template_name = "admin/style.html"
    title = "Style Guide"
    nav_section = None
