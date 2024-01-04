from bolt.urls import path


class AdminViewRegistry:
    def __init__(self):
        # View classes that will be added to the admin automatically
        self.registered_views = set()
        self.registered_dashboards = set()

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

    def register_dashboard(self, view=None):
        def inner(view):
            self.registered_dashboards.add(view)
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

    def get_nav_views(self):
        # class NavItem:
        #     def __init__(self, view, children):
        #         self.view = view
        #         self.children = children

        sorted_views = sorted(
            [view for view in self.registered_views if view.should_show_in_nav()],
            key=lambda v: v.get_title(),
        )

        return sorted_views

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
            urlpatterns.append(path(_path, view.as_view(), name=view.view_name()))

        for view in self.registered_views:
            add_view_path(view, f"p/{view.get_path()}")

        for view in self.registered_dashboards:
            add_view_path(view, f"dashboards/{view.get_path()}")

        return urlpatterns


registry = AdminViewRegistry()
register_view = registry.register_view
register_dashboard = registry.register_dashboard
register_viewset = registry.register_viewset
