from typing import TYPE_CHECKING

from bolt.db.models import Q
from bolt.urls import reverse_lazy

from .base import URL_NAMESPACE, AdminDetailView, AdminObjectsView, AdminUpdateView

if TYPE_CHECKING:
    from bolt.db import models

    from bolt.views import View


def get_model_field(instance, field):
    if "__" in field:
        # Allow __ syntax like querysets use,
        # also automatically calling callables (like __date)
        result = instance
        for part in field.split("__"):
            result = getattr(result, part)

            # If we hit a None, just return it
            if not result:
                return result

            if callable(result):
                result = result()

        return result

    # Automatically call get_FOO_display() if it exists
    if display := getattr(instance, f"get_{field}_display", None):
        return display()

    return getattr(instance, field)


class AdminModelListView(AdminObjectsView):
    show_search = True

    model: "models.Model"

    list_fields: list = ["pk"]
    list_order = []
    search_fields: list = ["pk"]

    def get_context(self):
        context = super().get_context()

        context["get_update_url"] = self.get_update_url
        context["get_detail_url"] = self.get_detail_url

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
        queryset = self.get_initial_queryset()
        queryset = self.order_queryset(queryset)
        queryset = self.search_queryset(queryset)
        return queryset

    def get_initial_queryset(self):
        # Separate override for the initial queryset
        # so that annotations can be added BEFORE order_by, etc.
        return self.model.objects.all()

    def order_queryset(self, queryset):
        if order_by := self.request.GET.get("order_by"):
            queryset = queryset.order_by(order_by)
        elif self.list_order:
            queryset = queryset.order_by(*self.list_order)

        return queryset

    def search_queryset(self, queryset):
        if search := self.request.GET.get("search"):
            filters = Q()
            for field in self.search_fields:
                filters |= Q(**{f"{field}__icontains": search})

            queryset = queryset.filter(filters)

        return queryset

    def get_update_url(self, object) -> str | None:
        return None

    def get_detail_url(self, object) -> str | None:
        return None

    def get_object_field(self, object, field: str):
        return get_model_field(object, field)


class AdminModelViewset:
    model: "models.Model"
    list_description = ""
    list_fields: list = ["pk"]
    list_order = []
    detail_fields: list = []
    search_fields = ["pk"]

    form_class = None  # TODO type annotation

    list_cards = []
    form_cards = []

    @classmethod
    def get_list_view(cls) -> AdminModelListView:
        class V(AdminModelListView):
            model = cls.model
            title = cls.model._meta.verbose_name_plural.capitalize()
            description = cls.list_description
            slug = cls.model._meta.model_name
            list_fields = cls.list_fields
            list_order = cls.list_order
            cards = cls.list_cards
            search_fields = cls.search_fields

            def get_update_url(self, object):
                update_view = cls.get_update_view()

                if not update_view:
                    return None

                # TODO a way to do this without explicit namespace?
                return reverse_lazy(
                    URL_NAMESPACE + ":" + update_view.view_name(),
                    kwargs={"pk": object.pk},
                )

            def get_detail_url(self, object):
                detail_view = cls.get_detail_view()

                if not detail_view:
                    return None

                return reverse_lazy(
                    URL_NAMESPACE + ":" + detail_view.view_name(),
                    kwargs={"pk": object.pk},
                )

            def get_initial_queryset(self):
                return cls.get_list_queryset(self)

        return V

    @classmethod
    def get_update_view(cls) -> AdminUpdateView | None:
        if not cls.form_class:
            return None

        class V(AdminUpdateView):
            title = f"Update {cls.model._meta.verbose_name}"
            slug = f"{cls.model._meta.model_name}_update"
            form_class = cls.form_class
            path = f"{cls.model._meta.model_name}/<int:pk>/update/"
            cards = cls.form_cards
            success_url = "."  # Redirect back to the same update page by default
            parent_view_class = cls.get_list_view()

            def get_object(self):
                return cls.model.objects.get(pk=self.url_kwargs["pk"])

        return V

    @classmethod
    def get_detail_view(cls) -> AdminDetailView | None:
        class V(AdminDetailView):
            title = cls.model._meta.verbose_name.capitalize()
            slug = f"{cls.model._meta.model_name}_detail"
            path = f"{cls.model._meta.model_name}/<int:pk>/"
            parent_view_class = cls.get_list_view()
            fields = cls.detail_fields

            def get_context(self):
                context = super().get_context()
                context["fields"] = self.fields or ["pk"] + [
                    f.name for f in self.object._meta.get_fields() if not f.remote_field
                ]
                return context

            def get_object(self):
                return cls.model.objects.get(pk=self.url_kwargs["pk"])

            def get_template_names(self) -> list[str]:
                return super().get_template_names() + [
                    "admin/object.html",
                ]

            def get_object_field(self, object, field: str):
                return get_model_field(object, field)

        return V

    @classmethod
    def get_views(cls) -> list["View"]:
        views = []

        if list_view := cls.get_list_view():
            views.append(list_view)

        if update_view := cls.get_update_view():
            views.append(update_view)

        if detail_view := cls.get_detail_view():
            views.append(detail_view)

        return views

    def get_list_queryset(self):
        # Can't use super() with this the way it works now
        return self.model.objects.all()
