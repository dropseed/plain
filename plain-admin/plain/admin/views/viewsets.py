from plain.views import View


class AdminViewset:
    @classmethod
    def get_views(cls) -> list[View]:
        """Views are defined as inner classes on the viewset class."""

        # Primary views that we can interlink automatically
        ListView = getattr(cls, "ListView", None)
        CreateView = getattr(cls, "CreateView", None)
        UpdateView = getattr(cls, "UpdateView", None)
        DetailView = getattr(cls, "DetailView", None)
        DeleteView = getattr(cls, "DeleteView", None)

        # Set parent-child view class relationships
        if ListView and CreateView:
            CreateView.parent_view_class = ListView

        if ListView and DetailView:
            DetailView.parent_view_class = ListView

        if DetailView and UpdateView:
            UpdateView.parent_view_class = DetailView

        if DetailView and DeleteView:
            DeleteView.parent_view_class = DetailView

        # Now iterate all inner view classes
        views = []

        for attr in cls.__dict__.values():
            if isinstance(attr, type) and issubclass(attr, View):
                views.append(attr)

        for view in views:
            view.viewset = cls

            if ListView:
                view.get_list_url = ListView.get_view_url

            if CreateView:
                view.get_create_url = CreateView.get_view_url

            if DetailView:
                view.get_detail_url = DetailView.get_view_url

            if UpdateView:
                view.get_update_url = UpdateView.get_view_url

            if DeleteView:
                view.get_delete_url = DeleteView.get_view_url

        return views
