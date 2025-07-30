from plain.urls import path, reverse_lazy


class AdminViewRegistry:
    def __init__(self):
        # View classes that will be added to the admin automatically
        self.registered_views = set()

    def register_view(self, view=None):
        def inner(view):
            self.registered_views.add(view)
            # TODO do this somewhere else...
            # self.registered_views = set(self.registered_views, key=lambda v: v.title)
            return view

        if callable(view):
            return inner(view)
        else:
            return inner

    def register_viewset(self, viewset=None):
        def inner(viewset):
            for view in viewset.get_views():
                self.register_view(view)
            return viewset

        if callable(viewset):
            return inner(viewset)
        else:
            return inner

    def get_app_nav_sections(self):
        """Returns nav sections for app/user packages only."""
        sections = {}

        for view in self.registered_views:
            # Skip plain package views
            if view.__module__.startswith("plain."):
                continue

            section = view.get_nav_section()

            # Skip views with nav_section = None (don't show in nav)
            if section is None:
                continue

            if section not in sections:
                sections[section] = []
            sections[section].append(view)

        # Sort each section by nav_title
        for section in sections.values():
            section.sort(key=lambda v: v.get_nav_title())

        # Sort sections alphabetically, but put empty string first
        def section_sort_key(item):
            section_name = item[0]
            return ("z" if section_name else "", section_name)

        return dict(sorted(sections.items(), key=section_sort_key))

    def get_plain_nav_sections(self):
        """Returns nav sections for plain packages only."""
        sections = {}

        for view in self.registered_views:
            # Only include plain package views
            if not view.__module__.startswith("plain."):
                continue

            section = view.get_nav_section()
            # Skip views with nav_section = None (don't show in nav)
            if section is None:
                continue

            if section not in sections:
                sections[section] = []
            sections[section].append(view)

        # Sort each section by nav_title
        for section in sections.values():
            section.sort(key=lambda v: v.get_nav_title())

        # Sort sections alphabetically
        return dict(sorted(sections.items()))

    def get_urls(self):
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

    def get_searchable_views(self):
        views = [
            view
            for view in self.registered_views
            if getattr(view, "allow_global_search", False)
        ]
        # Sort by slug since title isn't required by all views
        views.sort(key=lambda v: v.get_slug())
        return views

    def get_model_detail_url(self, instance):
        from plain.admin.views.base import URL_NAMESPACE
        from plain.admin.views.models import AdminModelDetailView

        if not getattr(instance, "id", None):
            # Has to actually be in the db
            return

        for view in self.registered_views:
            if not issubclass(view, AdminModelDetailView):
                continue

            if view.model == instance.__class__:
                return reverse_lazy(
                    f"{URL_NAMESPACE}:{view.view_name()}",
                    id=instance.id,
                )


registry = AdminViewRegistry()
register_view = registry.register_view
register_viewset = registry.register_viewset
get_model_detail_url = registry.get_model_detail_url
