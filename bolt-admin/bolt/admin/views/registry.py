from django.urls import path


class AdminViewRegistry:
    def __init__(self):
        # View classes that will be added to the admin automatically
        self.registered_views = set()
        self.registered_panels = set()

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

    def register_panel(self, panel=None):
        def inner(panel):
            # TODO make s
            self.registered_panels.add(panel)
            return panel

        if callable(panel):
            return inner(panel)
        else:
            return inner

    def register_model(self, viewset=None):
        def inner(viewset):
            for view in viewset.get_views():
                self.registered_views.add(view)
            return viewset

        if callable(viewset):
            return inner(viewset)
        else:
            return inner

    def get_urls(self):
        urlpatterns = []

        for view in self.registered_views:
            # TODO unique slugs
            urlpatterns.append(
                path(f"v/{view.get_path()}/", view.as_view(), name=view.view_name())
            )

        for view in self.registered_panels:
            # TODO unique slugs
            urlpatterns.append(
                path(
                    f"panels/{view.get_path()}/", view.as_view(), name=view.view_name()
                )
            )

        return urlpatterns


registry = AdminViewRegistry()
register_view = registry.register_view
register_panel = registry.register_panel
register_model = registry.register_model
