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

    def get_nav_sections(self):
        # class NavItem:
        #     def __init__(self, view, children):
        #         self.view = view
        #         self.children = children

        sections = {}

        for view in self.registered_views:
            section = view.get_nav_section()
            if not section:
                continue
            if section not in sections:
                sections[section] = []
            sections[section].append(view)

        # Sort each section by nav_title
        for section in sections.values():
            section.sort(key=lambda v: v.get_nav_title())

        # Sort sections dictionary by key
        sections = dict(sorted(sections.items()))

        return sections

        # root_nav_items = []

        # for view in sorted_views:
        #     if view.parent_view_class:
        #         continue
        #     children = [x for x in sorted_views if x.parent_view_class == view]
        #     root_nav_items.append(NavItem(view, children))

        # return root_nav_items

    def get_urls(self):
        urlpatterns = []

        paths_seen = set()

        def add_view_path(view, _path):
            if _path in paths_seen:
                raise ValueError(f"Path {_path} already registered")
            paths_seen.add(_path)
            if not _path.endswith("/"):
                _path += "/"
            urlpatterns.append(path(_path, view, name=view.view_name()))

        for view in self.registered_views:
            add_view_path(view, f"p/{view.get_path()}")

        return urlpatterns

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

        if not getattr(instance, "pk", None):
            # Has to actually be in the db
            return

        for view in self.registered_views:
            if not issubclass(view, AdminModelDetailView):
                continue

            if view.model == instance.__class__:
                return reverse_lazy(
                    f"{URL_NAMESPACE}:{view.view_name()}",
                    kwargs={"pk": instance.pk},
                )


registry = AdminViewRegistry()
register_view = registry.register_view
register_viewset = registry.register_viewset
get_model_detail_url = registry.get_model_detail_url
