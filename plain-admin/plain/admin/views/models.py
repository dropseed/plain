from __future__ import annotations

from typing import TYPE_CHECKING, Any

from plain import models
from plain.models import Q
from plain.models.exceptions import FieldDoesNotExist
from plain.models.fields.related_managers import BaseRelatedManager

from ..utils import camelcase_to_title
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
    allow_global_search = True

    model: type[models.Model]

    fields: list = ["id"]
    queryset_order = []
    search_fields: list = ["id"]

    def get_title(self) -> str:
        if title := super().get_title():
            return title

        return camelcase_to_title(self.model.model_options.object_name) + "s"

    @classmethod
    def get_nav_title(cls) -> str:
        if cls.nav_title:
            return cls.nav_title

        if cls.title:
            return cls.title

        return camelcase_to_title(cls.model.model_options.object_name) + "s"

    @classmethod
    def get_path(cls) -> str:
        if path := super().get_path():
            return path

        return f"{cls.model.model_options.model_name}/"

    def get_initial_objects(self) -> models.QuerySet:
        return self.get_initial_queryset()

    def get_initial_queryset(self) -> models.QuerySet:
        """Override this to customize the base queryset (e.g., add annotations)."""
        return self.model.query.all()

    def filter_objects(
        self, objects: models.QuerySet | list[Any]
    ) -> models.QuerySet | list[Any]:
        if isinstance(objects, list):
            return super().filter_objects(objects)
        return self.filter_queryset(objects)

    def filter_queryset(self, queryset: Any) -> Any:
        """Override this to filter the queryset based on self.filter."""
        return queryset

    def search_objects(
        self, objects: models.QuerySet | list[Any]
    ) -> models.QuerySet | list[Any]:
        if isinstance(objects, list):
            return super().search_objects(objects)
        return self.search_queryset(objects)

    def search_queryset(self, queryset: Any) -> Any:
        """Override this to customize search behavior."""
        if search := self.request.query_params.get("search"):
            filters = Q()
            for field in self.search_fields:
                filters |= Q(**{f"{field}__icontains": search})  # type: ignore[arg-type]
            return queryset.filter(filters)
        return queryset

    def order_objects(
        self, objects: models.QuerySet | list[Any]
    ) -> models.QuerySet | list[Any]:
        if isinstance(objects, list):
            return super().order_objects(objects)
        return self.order_queryset(objects)

    def order_queryset(self, queryset: Any) -> Any:
        """Override this to customize ordering behavior."""
        if order_by := self.request.query_params.get("order_by"):
            field_name = order_by.lstrip("-")

            # Check if this is a database field
            try:
                self.model._model_meta.get_field(field_name.split("__")[0])
                return queryset.order_by(order_by)
            except FieldDoesNotExist:
                pass

            # Check if it's an annotation on the queryset
            if field_name in queryset.sql_query.annotations:
                return queryset.order_by(order_by)

            # Method/property - sort in memory (limit to 1000 records)
            if field_name in self.get_fields():
                records = list(queryset[:1001])
                if len(records) > 1000:
                    raise ValueError(
                        f"Cannot sort by '{field_name}' - too many records for in-memory sorting. "
                        f"Use a database field or add an annotation."
                    )
                return super().order_objects(records)

        if self.queryset_order:
            return queryset.order_by(*self.queryset_order)

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

        return camelcase_to_title(cls.model.model_options.object_name)

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

        return f"New {camelcase_to_title(self.model.model_options.object_name).lower()}"

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

        return f"{cls.model.model_options.model_name}/<int:id>/edit/"

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
