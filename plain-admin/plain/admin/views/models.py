from __future__ import annotations

from typing import TYPE_CHECKING, Any

from plain import models
from plain.models import Q
from plain.models.fields.related_managers import BaseRelatedManager

from .objects import (
    AdminCreateView,
    AdminDeleteView,
    AdminDetailView,
    AdminListView,
    AdminUpdateView,
)

if TYPE_CHECKING:
    from plain import models
    from plain.forms import BaseForm


def get_model_field(instance: models.Model, field: str) -> Any:
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

    return getattr(instance, field)


class AdminModelListView(AdminListView):
    show_search = True
    allow_global_search = True

    model: type[models.Model]

    fields: list = ["id"]
    queryset_order = []
    search_fields: list = ["id"]

    def get_title(self) -> str:
        if title := super().get_title():
            return title

        return self.model.model_options.model_name.capitalize() + "s"

    @classmethod
    def get_nav_title(cls) -> str:
        if cls.nav_title:
            return cls.nav_title

        if cls.title:
            return cls.title

        return cls.model.model_options.model_name.capitalize() + "s"

    @classmethod
    def get_path(cls) -> str:
        if path := super().get_path():
            return path

        return f"{cls.model.model_options.model_name}/"

    def get_template_context(self) -> dict[str, Any]:
        context = super().get_template_context()

        order_by = self.request.query_params.get("order_by", "")
        if order_by.startswith("-"):
            order_by_field = order_by[1:]
            order_by_direction = "-"
        else:
            order_by_field = order_by
            order_by_direction = ""

        context["order_by_field"] = order_by_field
        context["order_by_direction"] = order_by_direction

        return context

    def get_objects(self) -> models.QuerySet:
        queryset = self.get_initial_queryset()
        queryset = self.search_queryset(queryset)
        queryset = self.order_queryset(queryset)
        return queryset

    def get_initial_queryset(self) -> models.QuerySet:
        # Separate override for the initial queryset
        # so that annotations can be added BEFORE order_by, etc.
        return self.model.query.all()

    def order_queryset(self, queryset: models.QuerySet) -> models.QuerySet:
        result = queryset
        if order_by := self.request.query_params.get("order_by"):
            # Let FieldError propagate - invalid fields should error
            # TODO: disable sorting on non-fields in the UI to prevent this
            result = queryset.order_by(order_by)
        elif self.queryset_order:
            result = queryset.order_by(*self.queryset_order)

        return result

    def search_queryset(self, queryset: models.QuerySet) -> models.QuerySet:
        if search := self.request.query_params.get("search"):
            filters = Q()
            for field in self.search_fields:
                filters |= Q(**{f"{field}__icontains": search})  # type: ignore[arg-type]

            queryset = queryset.filter(filters)

        return queryset

    def get_field_value(self, obj: Any, field: str) -> Any:
        try:
            value = super().get_field_value(obj, field)
            # Check if we got a related manager back and need to get its queryset
            if isinstance(value, BaseRelatedManager):
                return value.query.all()

            # For Model instances with choice fields, use get_field_display
            if isinstance(obj, models.Model):
                try:
                    field_obj = obj._model_meta.get_field(field)
                    if hasattr(field_obj, "flatchoices") and field_obj.flatchoices:
                        return obj.get_field_display(field)
                except Exception:
                    pass

            return value
        except (AttributeError, TypeError):
            return get_model_field(obj, field)


class AdminModelDetailView(AdminDetailView):
    model: type[models.Model]

    def get_title(self) -> str:
        return str(self.object)

    @classmethod
    def get_nav_title(cls) -> str:
        if cls.nav_title:
            return cls.nav_title

        if cls.title:
            return cls.title

        return cls.model.model_options.model_name.capitalize()

    @classmethod
    def get_path(cls) -> str:
        if path := super().get_path():
            return path

        return f"{cls.model.model_options.model_name}/<int:id>/"

    def get_fields(self) -> list[str]:
        if fields := super().get_fields():
            return fields

        return [f.name for f in self.object._model_meta.get_fields() if f.concrete]

    def get_field_value(self, obj: Any, field: str) -> Any:
        try:
            value = super().get_field_value(obj, field)
            # Check if we got a related manager back and need to get its queryset
            if isinstance(value, BaseRelatedManager):
                return value.query.all()

            # For Model instances with choice fields, use get_field_display
            if isinstance(obj, models.Model):
                try:
                    field_obj = obj._model_meta.get_field(field)
                    if hasattr(field_obj, "flatchoices") and field_obj.flatchoices:
                        return obj.get_field_display(field)
                except Exception:
                    pass

            return value
        except (AttributeError, TypeError):
            return get_model_field(obj, field)

    def get_object(self) -> models.Model:
        return self.model.query.get(id=self.url_kwargs["id"])


class AdminModelCreateView(AdminCreateView):
    model: type[models.Model]
    form_class: type[BaseForm] | None = None

    def get_title(self) -> str:
        if title := super().get_title():
            return title

        return f"New {self.model.model_options.model_name}"

    @classmethod
    def get_path(cls) -> str:
        if path := super().get_path():
            return path

        return f"{cls.model.model_options.model_name}/create/"


class AdminModelUpdateView(AdminUpdateView):
    model: type[models.Model]
    form_class: type[BaseForm] | None = None
    success_url = "."  # Redirect back to the same update page by default

    def get_title(self) -> str:
        if title := super().get_title():
            return title

        return f"Update {self.object}"

    @classmethod
    def get_path(cls) -> str:
        if path := super().get_path():
            return path

        return f"{cls.model.model_options.model_name}/<int:id>/update/"

    def get_object(self) -> models.Model:
        return self.model.query.get(id=self.url_kwargs["id"])


class AdminModelDeleteView(AdminDeleteView):
    model: type[models.Model]

    def get_title(self) -> str:
        return f"Delete {self.object}"

    @classmethod
    def get_path(cls) -> str:
        if path := super().get_path():
            return path

        return f"{cls.model.model_options.model_name}/<int:id>/delete/"

    def get_object(self) -> models.Model:
        return self.model.query.get(id=self.url_kwargs["id"])
