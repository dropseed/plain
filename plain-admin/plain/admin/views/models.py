from typing import TYPE_CHECKING, Any

from plain.exceptions import ValidationError
from plain.postgres import Q
from plain.postgres.exceptions import FieldDoesNotExist, ObjectDoesNotExist
from plain.postgres.fields.related_managers import BaseRelatedManager

from plain import postgres

from ..field_refs import FieldRef, converge_declared_tuple, field_lookup_paths
from ..utils import camelcase_to_title
from .objects import (
    AdminCreateView,
    AdminDeleteView,
    AdminDetailView,
    AdminListView,
    AdminUpdateView,
)

if TYPE_CHECKING:
    from plain.forms import BaseForm


def get_model_field(instance: postgres.Model, field: str) -> Any:
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
    allow_global_search = False

    model: type[postgres.Model]

    fields: tuple[str, ...] = ("id",)
    # Field references (`User.email`, `FlagResult.flag.name`) or lookup paths.
    # A reference has to belong to `model`; a path that traversal can't reach
    # -- a reverse or many-to-many hop -- is spelled as a string.
    queryset_order: tuple[FieldRef, ...] = ()
    search_fields: tuple[FieldRef, ...] = ("id",)

    # Filter *names* shown in the UI, not fields. Can also be a dict mapping a
    # filter name to a Q object, which filters the queryset automatically.
    filters: tuple[str, ...] | dict[str, Q] = ()

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        # Normalize the declared field references now, so a reference to
        # another model's field is a TypeError at class definition rather than
        # when the page is first rendered, and so no `Field` is left sitting
        # on the class as a live descriptor. An intermediate subclass with no
        # model yet is still normalized -- only the cross-model check needs
        # the model.
        model = getattr(cls, "model", None)
        converge_declared_tuple(cls, "search_fields", model=model)
        converge_declared_tuple(cls, "queryset_order", model=model)

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

    def get_initial_objects(self) -> postgres.QuerySet:
        return self.get_initial_queryset()

    def get_initial_queryset(self) -> postgres.QuerySet:
        """Override this to customize the base queryset (e.g., add annotations)."""
        return self.model.query.all()

    def get_filter_names(self) -> tuple[str, ...]:
        """Return filter names. Supports both tuple[str, ...] and dict[str, Q] formats."""
        filters = self.filters
        if isinstance(filters, dict):
            return tuple(filters.keys())
        return super().get_filter_names()

    def get_search_fields(self) -> tuple[str, ...]:
        """`search_fields` as lookup paths, checked against the view's model."""
        return field_lookup_paths(
            self.search_fields,
            model=self.model,
            declared_as=f"{type(self).__qualname__}.search_fields",
        )

    def get_queryset_order(self) -> tuple[str, ...]:
        """`queryset_order` as lookup paths, checked against the view's model.

        A descending term stays a string -- a field reference has no direction
        to carry, so `"-created_at"` is the only way to write one.
        """
        return field_lookup_paths(
            self.queryset_order,
            model=self.model,
            declared_as=f"{type(self).__qualname__}.queryset_order",
        )

    def filter_objects(
        self, objects: postgres.QuerySet | list[Any]
    ) -> postgres.QuerySet | list[Any]:
        if isinstance(objects, list):
            return super().filter_objects(objects)
        return self.filter_queryset(objects)

    def filter_queryset(self, queryset: Any) -> Any:
        """Filter the queryset based on self.filter.

        When filters is a dict[str, Q], matching is handled automatically.
        Override this for custom filter logic when using list[str] filters.
        """
        if isinstance(self.filters, dict) and self.filter:
            q = self.filters.get(self.filter)
            if q is not None:
                # filter(), not where(): this Q comes from user configuration,
                # so it names no model for where()'s check to test, and
                # `queryset` is untyped here anyway.
                return queryset.filter(q)
        return queryset

    def search_objects(
        self, objects: postgres.QuerySet | list[Any]
    ) -> postgres.QuerySet | list[Any]:
        if isinstance(objects, list):
            return super().search_objects(objects)
        return self.search_queryset(objects)

    def search_queryset(self, queryset: Any) -> Any:
        """Override this to customize search behavior."""
        if search := self.request.query_params.get("search"):
            filters = Q()
            for field in self.get_search_fields():
                filters |= Q(**{f"{field}__icontains": search})  # ty: ignore[invalid-argument-type]
            return queryset.filter(filters)
        return queryset

    def select_objects_by_id(
        self, objects: postgres.QuerySet | list[Any], ids: list[str]
    ) -> postgres.QuerySet | list[Any]:
        if isinstance(objects, list):
            return super().select_objects_by_id(objects, ids)
        # get_object_id() returns the primary key, so we match on it and keep
        # the queryset lazy. Coerce each id through the pk field and drop the
        # ones it rejects, so a stale or malformed id is ignored (per the base
        # contract) rather than raising.
        #
        # Everything reads the pk field off `objects.model` rather than
        # `self.model`: a subclass is free to return another model's queryset
        # from get_initial_queryset(), and where() rejects a condition built
        # from a model the queryset isn't querying.
        pk_field = objects.model.id
        valid_ids: list[int] = []
        for raw_id in ids:
            try:
                coerced = pk_field.to_python(raw_id)
            except ValidationError:
                continue
            # to_python is typed `int | None` but only returns None for a None
            # input, which form data can't produce -- this narrows the type,
            # it doesn't drop anything.
            if coerced is not None:
                valid_ids.append(coerced)
        return objects.where(pk_field.is_in(valid_ids))

    def order_objects(
        self, objects: postgres.QuerySet | list[Any]
    ) -> postgres.QuerySet | list[Any]:
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

        if queryset_order := self.get_queryset_order():
            return queryset.order_by(*queryset_order)

        return queryset

    def get_field_value(self, obj: Any, field: str) -> Any:
        try:
            value = super().get_field_value(obj, field)
            # Check if we got a related manager back and need to get its queryset
            if isinstance(value, BaseRelatedManager):
                return value.query.all()

            # For Model instances with choice fields, use get_field_display
            if isinstance(obj, postgres.Model):
                try:
                    field_obj = obj._model_meta.get_field(field)
                    if hasattr(field_obj, "flatchoices") and field_obj.flatchoices:
                        return obj.get_field_display(field)
                except FieldDoesNotExist, ObjectDoesNotExist:
                    # ObjectDoesNotExist: get_field_display can refresh a
                    # deferred field, racing a concurrent delete — fall back
                    # to the raw value.
                    pass

            return value
        except AttributeError, TypeError:
            return get_model_field(obj, field)


class AdminModelDetailView(AdminDetailView):
    model: type[postgres.Model]

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

    def get_fields(self) -> tuple[str, ...]:
        if fields := super().get_fields():
            return fields

        return tuple(f.name for f in self.object._model_meta.get_fields())

    def get_field_value(self, obj: Any, field: str) -> Any:
        try:
            value = super().get_field_value(obj, field)
            # Check if we got a related manager back and need to get its queryset
            if isinstance(value, BaseRelatedManager):
                return value.query.all()

            # For Model instances with choice fields, use get_field_display
            if isinstance(obj, postgres.Model):
                try:
                    field_obj = obj._model_meta.get_field(field)
                    if hasattr(field_obj, "flatchoices") and field_obj.flatchoices:
                        return obj.get_field_display(field)
                except FieldDoesNotExist, ObjectDoesNotExist:
                    # ObjectDoesNotExist: get_field_display can refresh a
                    # deferred field, racing a concurrent delete — fall back
                    # to the raw value.
                    pass

            return value
        except AttributeError, TypeError:
            return get_model_field(obj, field)

    def get_object(self) -> postgres.Model:
        return self.model.query.get(self.url_kwargs["id"])


class AdminModelCreateView(AdminCreateView):
    model: type[postgres.Model]
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
    model: type[postgres.Model]
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

    def get_object(self) -> postgres.Model:
        return self.model.query.get(self.url_kwargs["id"])


class AdminModelDeleteView(AdminDeleteView):
    model: type[postgres.Model]

    def get_title(self) -> str:
        return f"Delete {self.object}"

    @classmethod
    def get_path(cls) -> str:
        if path := super().get_path():
            return path

        return f"{cls.model.model_options.model_name}/<int:id>/delete/"

    def get_object(self) -> postgres.Model:
        return self.model.query.get(self.url_kwargs["id"])
