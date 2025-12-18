"""
"Rel objects" for related fields.

"Rel objects" (for lack of a better name) carry information about the relation
modeled by a related field and provide some utility functions. They're stored
in the ``remote_field`` attribute of the field.

They also act as reverse fields for the purposes of the Meta API because
they're the closest concept currently available.
"""

from __future__ import annotations

from functools import cached_property
from typing import TYPE_CHECKING, Any

from plain.models.exceptions import FieldError
from plain.utils.hashable import make_hashable

from . import BLANK_CHOICE_DASH
from .mixins import FieldCacheMixin

if TYPE_CHECKING:
    from collections.abc import Callable

    from plain.models.base import Model
    from plain.models.deletion import Collector
    from plain.models.fields import Field
    from plain.models.fields.related import (
        ForeignKeyField,
        ManyToManyField,
        RelatedField,
    )
    from plain.models.lookups import Lookup
    from plain.models.query_utils import PathInfo, Q

    # Type alias for on_delete callbacks
    OnDeleteCallback = Callable[[Collector, Any, Any], None]


class ForeignObjectRel(FieldCacheMixin):
    """
    Used by ForeignKeyField to store information about the relation.

    ``_model_meta.get_fields()`` returns this class to provide access to the field
    flags for the reverse relation.
    """

    # Field flags
    auto_created = True
    concrete = False

    # Reverse relations are always nullable (Plain can't enforce that a
    # foreign key on the related model points to this model).
    allow_null = True
    empty_strings_allowed = False

    # Type annotations for instance attributes
    model: type[Model]
    field: RelatedField
    on_delete: OnDeleteCallback | None
    limit_choices_to: dict[str, Any] | Q

    def __init__(
        self,
        field: RelatedField,
        to: str | type[Model],
        related_query_name: str | None = None,
        limit_choices_to: dict[str, Any] | Q | None = None,
        on_delete: OnDeleteCallback | None = None,
    ):
        self.field = field  # type: ignore[misc]
        # Initially may be a string, gets resolved to type[Model] by lazy_related_operation
        # (see related.py:250 where field.remote_field.model is overwritten)
        self.model = to  # type: ignore[assignment]
        self.related_query_name = related_query_name
        self.limit_choices_to = {} if limit_choices_to is None else limit_choices_to
        self.on_delete = on_delete

        self.symmetrical = False
        self.multiple = True

    # Some of the following cached_properties can't be initialized in
    # __init__ as the field doesn't have its model yet. Calling these methods
    # before field.contribute_to_class() has been called will result in
    # AttributeError
    @cached_property
    def name(self) -> str:
        return self.field.related_query_name()

    @property
    def remote_field(self) -> RelatedField:
        return self.field

    @property
    def target_field(self) -> Field:
        """
        When filtering against this relation, return the field on the remote
        model against which the filtering should happen.
        """
        target_fields = self.path_infos[-1].target_fields
        if len(target_fields) > 1:
            raise FieldError("Can't use target_field for multicolumn relations.")
        return target_fields[0]

    @cached_property
    def related_model(self) -> type[Model]:
        if not self.field.model:
            raise AttributeError(
                "This property can't be accessed before self.field.contribute_to_class "
                "has been called."
            )
        return self.field.model

    def get_lookup(self, lookup_name: str) -> type[Lookup] | None:
        return self.field.get_lookup(lookup_name)

    def get_internal_type(self) -> str:
        return self.field.get_internal_type()

    @property
    def db_type(self) -> str | None:
        return self.field.db_type

    def __repr__(self) -> str:
        return f"<{type(self).__name__}: {self.related_model.model_options.package_label}.{self.related_model.model_options.model_name}>"

    @property
    def identity(self) -> tuple[Any, ...]:
        return (
            self.field,
            self.model,
            self.related_query_name,
            make_hashable(self.limit_choices_to),
            self.on_delete,
            self.symmetrical,
            self.multiple,
        )

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, self.__class__):
            return NotImplemented
        return self.identity == other.identity

    def __hash__(self) -> int:
        return hash(self.identity)

    def __getstate__(self) -> dict[str, Any]:
        state = self.__dict__.copy()
        # Delete the path_infos cached property because it can be recalculated
        # at first invocation after deserialization. The attribute must be
        # removed because subclasses like ForeignKeyRel may have a PathInfo
        # which contains an intermediate M2M table that's been dynamically
        # created and doesn't exist in the .models module.
        # This is a reverse relation, so there is no reverse_path_infos to
        # delete.
        state.pop("path_infos", None)
        return state

    def get_choices(
        self,
        include_blank: bool = True,
        blank_choice: list[tuple[str, str]] = BLANK_CHOICE_DASH,
        limit_choices_to: Any = None,
        ordering: tuple[str, ...] = (),
    ) -> list[tuple[Any, str]]:
        """
        Return choices with a default blank choices included, for use
        as <select> choices for this field.

        Analog of plain.models.fields.Field.get_choices(), provided
        initially for utilization by RelatedFieldListFilter.
        """
        limit_choices_to = limit_choices_to or self.limit_choices_to
        qs = self.related_model.query.complex_filter(limit_choices_to)
        if ordering:
            qs = qs.order_by(*ordering)
        return (blank_choice if include_blank else []) + [(x.id, str(x)) for x in qs]

    def get_joining_columns(self) -> tuple[tuple[str, str], ...]:
        return self.field.get_reverse_joining_columns()

    def set_field_name(self) -> None:
        """
        Set the related field's name, this is not available until later stages
        of app loading, so set_field_name is called from
        set_attributes_from_rel()
        """
        # By default foreign object doesn't relate to any remote field (for
        # example custom multicolumn joins currently have no remote field).
        self.field_name = None

    def get_path_info(self, filtered_relation: Any = None) -> list[PathInfo]:
        if filtered_relation:
            return self.field.get_reverse_path_info(filtered_relation)
        else:
            return self.field.reverse_path_infos

    @cached_property
    def path_infos(self) -> list[PathInfo]:
        return self.get_path_info()

    def get_cache_name(self) -> str:
        """
        Return the name of the cache key to use for storing an instance of the
        forward model on the reverse model.

        Uses the related_query_name for caching, which provides a stable name
        for prefetch_related operations.
        """
        return self.field.related_query_name()


class ForeignKeyRel(ForeignObjectRel):
    """
    Used by the ForeignKeyField field to store information about the relation.

    ``_model_meta.get_fields()`` returns this class to provide access to the
    reverse relation. Use ``isinstance(rel, ForeignKeyRel)`` to identify
    one-to-many reverse relations.
    """

    # Type annotations for instance attributes
    field: ForeignKeyField

    def __init__(
        self,
        field: ForeignKeyField,
        to: str | type[Model],
        related_query_name: str | None = None,
        limit_choices_to: dict[str, Any] | Q | None = None,
        on_delete: OnDeleteCallback | None = None,
    ):
        super().__init__(
            field,
            to,
            related_query_name=related_query_name,
            limit_choices_to=limit_choices_to,
            on_delete=on_delete,
        )

        self.field_name = "id"

    def __getstate__(self) -> dict[str, Any]:
        state = super().__getstate__()
        state.pop("related_model", None)
        return state

    @property
    def identity(self) -> tuple[Any, ...]:
        return super().identity + (self.field_name,)

    def get_related_field(self) -> Field:
        """
        Return the Field in the 'to' object to which this relationship is tied.
        """
        return self.model._model_meta.get_forward_field("id")

    def set_field_name(self) -> None:
        pass


class ManyToManyRel(ForeignObjectRel):
    """
    Used by ManyToManyField to store information about the relation.

    ``_model_meta.get_fields()`` returns this class to provide access to the field
    flags for the reverse relation.
    """

    # Type annotations for instance attributes
    field: ManyToManyField
    through: type[Model]
    through_fields: tuple[str, str] | None

    def __init__(
        self,
        field: ManyToManyField,
        to: str | type[Model],
        *,
        through: str | type[Model],
        through_fields: tuple[str, str] | None = None,
        related_query_name: str | None = None,
        limit_choices_to: dict[str, Any] | Q | None = None,
        symmetrical: bool = True,
    ):
        super().__init__(
            field,
            to,
            related_query_name=related_query_name,
            limit_choices_to=limit_choices_to,
        )

        # Initially may be a string, gets resolved to type[Model] by lazy_related_operation
        # (see related.py:1143 where field.remote_field.through is overwritten)
        self.through = through  # type: ignore[assignment]
        self.through_fields = through_fields

        self.symmetrical = symmetrical
        self.db_constraint = True

    @property
    def identity(self) -> tuple[Any, ...]:
        return super().identity + (
            self.through,
            make_hashable(self.through_fields),
            self.db_constraint,
        )

    def get_related_field(self) -> Field:
        """
        Return the field in the 'to' object to which this relationship is tied.
        Provided for symmetry with ForeignKeyRel.
        """
        from plain.models.fields.related import ForeignKeyField

        meta = self.through._model_meta
        if self.through_fields:
            field = meta.get_forward_field(self.through_fields[0])
        else:
            for field in meta.fields:
                rel = getattr(field, "remote_field", None)
                if rel and rel.model == self.model:
                    break

        if not isinstance(field, ForeignKeyField):
            raise ValueError(f"Expected ForeignKeyField, got {type(field)}")
        return field.foreign_related_fields[0]
