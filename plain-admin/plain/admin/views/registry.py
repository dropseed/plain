from collections.abc import Callable
from typing import Any, TypeVar

from plain.urls import path, reverse_lazy

T = TypeVar("T")


class NavSection:
    def __init__(self, name: str, icon: str = "folder"):
        self.name = name
        self.icon = icon

    def __str__(self) -> str:
        return self.name

    def __eq__(self, other: Any) -> bool:
        if isinstance(other, NavSection):
            return self.name == other.name
        return self.name == other

    def __hash__(self) -> int:
        return hash(self.name)


class AdminViewRegistry:
    def __init__(self):
        # View classes that will be added to the admin automatically
        self.registered_views = set()

    def register_view(
        self, view: type[T] | None = None
    ) -> type[T] | Callable[[type[T]], type[T]]:
        def inner(view: type[T]) -> type[T]:
            self.registered_views.add(view)
            # TODO do this somewhere else...
            # self.registered_views = set(self.registered_views, key=lambda v: v.title)
            return view

        if callable(view):
            return inner(view)
        else:
            return inner

    def register_viewset(
        self, viewset: type[T] | None = None
    ) -> type[T] | Callable[[type[T]], type[T]]:
        def inner(viewset: type[T]) -> type[T]:
            for view in viewset.get_views():
                self.register_view(view)
            return viewset

        if callable(viewset):
            return inner(viewset)
        else:
            return inner

    def get_app_nav_sections(self) -> dict[NavSection, list[type]]:
        """Returns nav sections for app/user packages only."""
        sections: dict[NavSection, list[type]] = {}
        section_icons: dict[str, str] = {}  # Track icons per section

        for view in self.registered_views:
            # Skip plain package views
            if view.__module__.startswith("plain."):
                continue

            section_name = view.nav_section

            # Skip views with nav_section = None (don't show in nav)
            # But allow empty string "" for ungrouped items
            if section_name is None:
                continue

            # Set section icon if this view defines one and we don't have one yet
            if view.nav_icon and section_name not in section_icons:
                section_icons[section_name] = view.nav_icon

            # Create or get the NavSection
            section_icon = section_icons.get(section_name, "folder")
            nav_section = NavSection(section_name, section_icon)

            if nav_section not in sections:
                sections[nav_section] = []
            sections[nav_section].append(view)

        # Sort each section by nav_title
        for section in sections.values():
            section.sort(key=lambda v: v.get_nav_title())

        # Sort sections alphabetically, but put empty string first
        def section_sort_key(item: tuple[NavSection, list[type]]) -> tuple[str, str]:
            section_name = item[0].name
            return ("z" if section_name else "", section_name)

        return dict(sorted(sections.items(), key=section_sort_key))

    def get_plain_nav_sections(self) -> dict[NavSection, list[type]]:
        """Returns nav sections for plain packages only."""
        sections: dict[NavSection, list[type]] = {}
        section_icons: dict[str, str] = {}  # Track icons per section

        for view in self.registered_views:
            # Only include plain package views
            if not view.__module__.startswith("plain."):
                continue

            section_name = view.nav_section
            # Skip views with nav_section = None (don't show in nav)
            # But allow empty string "" for ungrouped items
            if section_name is None:
                continue

            # Set section icon if this view defines one and we don't have one yet
            if view.nav_icon and section_name not in section_icons:
                section_icons[section_name] = view.nav_icon

            # Create or get the NavSection
            section_icon = section_icons.get(section_name, "folder")
            nav_section = NavSection(section_name, section_icon)

            if nav_section not in sections:
                sections[nav_section] = []
            sections[nav_section].append(view)

        # Sort each section by nav_title
        for section in sections.values():
            section.sort(key=lambda v: v.get_nav_title())

        # Sort sections alphabetically
        return dict(sorted(sections.items(), key=lambda item: item[0].name))

    def get_urls(self) -> list:
        urls = []

        paths_seen = {}

        for view in self.registered_views:
            view_path = view.get_path()

            if not view_path:
                raise ValueError(f"Path for {view} is empty")

            if existing_view := paths_seen.get(view_path, None):
                raise ValueError(
                    f"Duplicate admin path {view_path}\n{existing_view}\n{view}"
                )

            paths_seen[view_path] = view

            # Append trailing slashes automatically
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
        # Sort by slug since title isn't required by all views
        views.sort(key=lambda v: v.get_slug())
        return views

    def get_model_detail_url(self, instance: Any) -> str | None:
        from plain.admin.views.base import URL_NAMESPACE
        from plain.admin.views.models import AdminModelDetailView

        if not getattr(instance, "id", None):
            # Has to actually be in the db
            return None

        for view in self.registered_views:
            if not issubclass(view, AdminModelDetailView):
                continue

            if view.model == instance.__class__:
                return reverse_lazy(
                    f"{URL_NAMESPACE}:{view.view_name()}",
                    id=instance.id,
                )
        return None


registry = AdminViewRegistry()
register_view = registry.register_view
register_viewset = registry.register_viewset
get_model_detail_url = registry.get_model_detail_url
