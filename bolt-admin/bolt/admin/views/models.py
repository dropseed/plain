from typing import TYPE_CHECKING

from django.db.models import Q
from django.urls import reverse_lazy

from .base import URL_NAMESPACE, AdminObjectsView, AdminUpdateView

if TYPE_CHECKING:
    from django.db import models

    from bolt.views import View


class AdminModelListView(AdminObjectsView):
    show_search = True

    model: "models.Model"

    list_fields: list = ["pk"]
    list_order = []
    search_fields: list = ["pk"]

    def get_context(self):
        context = super().get_context()

        context["get_update_url"] = self.get_update_url

        order_by = self.request.GET.get("order_by", "")
        if order_by.startswith("-"):
            order_by_field = order_by[1:]
            order_by_direction = "-"
        else:
            order_by_field = order_by
            order_by_direction = ""

        context["order_by_field"] = order_by_field
        context["order_by_direction"] = order_by_direction

        return context

    def get_objects(self):
        queryset = self.model.objects.all()

        if order_by := self.request.GET.get("order_by"):
            queryset = queryset.order_by(order_by)
        elif self.list_order:
            queryset = queryset.order_by(*self.list_order)

        if search := self.request.GET.get("search"):
            filters = Q()
            for field in self.search_fields:
                filters |= Q(**{f"{field}__icontains": search})
            print(filters)

            queryset = queryset.filter(filters)

        return queryset

    def get_update_url(self, object) -> str | None:
        return None


class AdminModelViewset:
    model: "models.Model"
    list_fields: list = ["pk"]
    list_order = []
    search_fields = ["pk"]

    form_class = None  # TODO type annotation

    list_panels = []
    form_panels = []

    @classmethod
    def get_list_view(cls) -> AdminModelListView:
        class V(AdminModelListView):
            model = cls.model
            title = cls.model._meta.verbose_name_plural.capitalize()
            slug = cls.model._meta.model_name
            list_fields = cls.list_fields
            list_order = cls.list_order
            panels = cls.list_panels
            search_fields = cls.search_fields

            def get_update_url(self, object):
                if not cls.form_class:
                    return None

                # TODO a way to do this without explicit namespace?
                return reverse_lazy(
                    URL_NAMESPACE + ":" + cls.get_update_view().view_name(),
                    kwargs={"pk": object.pk},
                )

        return V

    @classmethod
    def get_update_view(cls) -> AdminUpdateView | None:
        if not cls.form_class:
            return None

        class V(AdminUpdateView):
            title = cls.model._meta.verbose_name.capitalize()
            slug = f"{cls.model._meta.model_name}_update"
            form_class = cls.form_class
            path = f"{cls.model._meta.model_name}/<int:pk>"
            panels = cls.form_panels

            def get_object(self):
                return cls.model.objects.get(pk=self.url_kwargs["pk"])

        return V

    @classmethod
    def get_views(cls) -> list["View"]:
        views = []

        if list_view := cls.get_list_view():
            views.append(list_view)

        if update_view := cls.get_update_view():
            views.append(update_view)

        return views
