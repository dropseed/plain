from __future__ import annotations

from collections.abc import Callable
from functools import cached_property
from typing import TYPE_CHECKING, Any, TypeVar

from plain.auth import get_request_user
from plain.sessions import get_request_session
from plain.urls import path, reverse_lazy

if TYPE_CHECKING:
    from plain.http import Request

    from .base import AdminView
    from .viewsets import AdminViewset

T = TypeVar("T")
VS = TypeVar("VS", bound="AdminViewset")


class AdminViewRegistry:
    def __init__(self) -> None:
        self.registered_views: set[type[AdminView]] = set()

    @cached_property
    def slug_to_view(self) -> dict[str, type[AdminView]]:
        """Slug -> view lookup dict, built once on first access."""
        return {view.get_slug(): view for view in self.registered_views}

    def register_view(
        self, view: type[T] | None = None
    ) -> type[T] | Callable[[type[T]], type[T]]:
        def inner(view: type[T]) -> type[T]:
            self.registered_views.add(view)  # type: ignore[arg-type]
            # Invalidate slug lookup cache
            self.__dict__.pop("slug_to_view", None)
            return view

        if callable(view):
            return inner(view)
        else:
            return inner

    def register_viewset(
        self, viewset: type[VS] | None = None
    ) -> type[VS] | Callable[[type[VS]], type[VS]]:
        def inner(viewset: type[VS]) -> type[VS]:
            for view in viewset.get_views():
                self.register_view(view)
            return viewset

        if callable(viewset):
            return inner(viewset)
        else:
            return inner

    def get_nav_sections(self, *, plain_packages: bool) -> dict[str, list[type]]:
        """Returns nav sections filtered by package type."""
        sections: dict[str, list[type]] = {}

        for view in self.registered_views:
            is_plain = view.__module__.startswith("plain.")
            if is_plain != plain_packages:
                continue

            if view.nav_section is None:
                continue

            sections.setdefault(view.nav_section, []).append(view)

        # Sort views within each section
        for views in sections.values():
            views.sort(key=lambda v: v.get_nav_title())

        # Sort sections alphabetically (empty string first for app sections)
        if plain_packages:
            return dict(sorted(sections.items()))
        else:
            return dict(
                sorted(sections.items(), key=lambda x: ("z" if x[0] else "", x[0]))
            )

    def get_urls(self) -> list:
        urls = []
        paths_seen = {}

        for view in self.registered_views:
            view_path = view.get_path()

            if not view_path:
                raise ValueError(f"Path for {view} is empty")

            if existing_view := paths_seen.get(view_path):
                raise ValueError(
                    f"Duplicate admin path {view_path}\n{existing_view}\n{view}"
                )

            paths_seen[view_path] = view

            if not view_path.endswith("/"):
                view_path += "/"

            urls.append(path(f"p/{view_path}", view, name=view.view_name()))

        return urls

    def get_searchable_views(self) -> list[type]:
        views = [
            view
            for view in self.registered_views
            if getattr(view, "allow_global_search", False)
        ]
        views.sort(key=lambda v: v.get_slug())
        return views

    def get_model_detail_url(self, instance: Any) -> str | None:
        from plain.admin.views.base import _URL_NAMESPACE
        from plain.admin.views.models import AdminModelDetailView

        if not getattr(instance, "id", None):
            return None

        for view in self.registered_views:
            if not issubclass(view, AdminModelDetailView):
                continue

            if view.model == instance.__class__:
                return reverse_lazy(
                    f"{_URL_NAMESPACE}:{view.view_name()}",
                    id=instance.id,
                )
        return None

    def get_view_by_slug(self, slug: str) -> type[AdminView] | None:
        """Look up a view by its slug."""
        return self.slug_to_view.get(slug)

    def get_nav_tabs(
        self,
        request: Request,
        max_tabs: int = 7,
        max_pinned: int = 6,
    ) -> list[dict[str, Any]]:
        """Build navigation tabs: pinned items first, then recent pages."""
        from plain.admin.models import PinnedNavItem

        user = get_request_user(request)
        session = get_request_session(request)

        # Get pinned items (ordered)
        if user:
            pinned_slugs = list(
                PinnedNavItem.query.filter(user=user)
                .order_by("order", "created_at")
                .values_list("view_slug", flat=True)[:max_pinned]
            )
        else:
            pinned_slugs = []

        # Get recent items from session
        recent_slugs: list[str] = session.get("admin_recent_nav", [])

        # Build tab list
        tabs: list[dict[str, Any]] = []
        used_slugs: set[str] = set()

        # Add pinned first
        for slug in pinned_slugs:
            if view := self.get_view_by_slug(slug):
                if view.nav_section is None:
                    continue
                tabs.append({"view": view, "pinned": True})
                used_slugs.add(slug)

        # Fill remaining slots with recent
        for slug in recent_slugs:
            if len(tabs) >= max_tabs:
                break
            if slug not in used_slugs:
                if view := self.get_view_by_slug(slug):
                    if view.nav_section is None:
                        continue
                    tabs.append({"view": view, "pinned": False})
                    used_slugs.add(slug)

        return tabs[:max_tabs]


def track_recent_nav(request: Request, view_slug: str, max_items: int = 20) -> None:
    """Track a page visit in the session for recent nav tabs."""
    session = get_request_session(request)
    recent: list[str] = session.get("admin_recent_nav", [])

    # Move to front
    if view_slug in recent:
        recent.remove(view_slug)
    recent.insert(0, view_slug)

    session["admin_recent_nav"] = recent[:max_items]


registry = AdminViewRegistry()
register_view = registry.register_view
register_viewset = registry.register_viewset
get_model_detail_url = registry.get_model_detail_url
