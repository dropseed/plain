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
from typing import Any

from plain.models.exceptions import FieldDoesNotExist, FieldError
from plain.utils.hashable import make_hashable

from . import BLANK_CHOICE_DASH
from .mixins import FieldCacheMixin


class ForeignObjectRel(FieldCacheMixin):
    """
    Used by ForeignKey to store information about the relation.

    ``_model_meta.get_fields()`` returns this class to provide access to the field
    flags for the reverse relation.
    """

    # Field flags
    auto_created = True
    concrete = False
    is_relation = True

    # Reverse relations are always nullable (Plain can't enforce that a
    # foreign key on the related model points to this model).
    allow_null = True
    empty_strings_allowed = False

    def __init__(
        self,
        field: Any,
        to: Any,
        related_name: str | None = None,
        related_query_name: str | None = None,
        limit_choices_to: Any = None,
        on_delete: Any = None,
    ):
        self.field = field
        self.model = to
        self.related_name = related_name
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
    def hidden(self) -> bool:
        return self.is_hidden()

    @cached_property
    def name(self) -> str:
        return self.field.related_query_name()

    @property
    def remote_field(self) -> Any:
        return self.field

    @property
    def target_field(self) -> Any:
        """
        When filtering against this relation, return the field on the remote
        model against which the filtering should happen.
        """
        target_fields = self.path_infos[-1].target_fields
        if len(target_fields) > 1:
            raise FieldError("Can't use target_field for multicolumn relations.")
        return target_fields[0]

    @cached_property
    def related_model(self) -> Any:
        if not self.field.model:
            raise AttributeError(
                "This property can't be accessed before self.field.contribute_to_class "
                "has been called."
            )
        return self.field.model

    @cached_property
    def many_to_many(self) -> bool:
        return self.field.many_to_many

    @cached_property
    def many_to_one(self) -> bool:
        return self.field.one_to_many

    @cached_property
    def one_to_many(self) -> bool:
        return self.field.many_to_one

    def get_lookup(self, lookup_name: str) -> Any:
        return self.field.get_lookup(lookup_name)

    def get_internal_type(self) -> str:
        return self.field.get_internal_type()

    @property
    def db_type(self) -> Any:
        return self.field.db_type

    def __repr__(self) -> str:
        return f"<{type(self).__name__}: {self.related_model.model_options.package_label}.{self.related_model.model_options.model_name}>"

    @property
    def identity(self) -> tuple[Any, ...]:
        return (
            self.field,
            self.model,
            self.related_name,
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
        # removed because subclasses like ManyToOneRel may have a PathInfo
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

    def is_hidden(self) -> bool:
        """Should the related object be hidden?"""
        return not self.related_name

    def get_joining_columns(self) -> Any:
        return self.field.get_reverse_joining_columns()

    def get_extra_restriction(self, alias: str, related_alias: str) -> Any:
        return self.field.get_extra_restriction(related_alias, alias)

    def set_field_name(self) -> None:
        """
        Set the related field's name, this is not available until later stages
        of app loading, so set_field_name is called from
        set_attributes_from_rel()
        """
        # By default foreign object doesn't relate to any remote field (for
        # example custom multicolumn joins currently have no remote field).
        self.field_name = None

    def get_accessor_name(self, model: Any = None) -> str | None:
        # This method encapsulates the logic that decides what name to give an
        # accessor descriptor that retrieves related many-to-one or
        # many-to-many objects.
        model = model or self.related_model
        if self.multiple:
            # If this is a symmetrical m2m relation on self, there is no
            # reverse accessor.
            if self.symmetrical and model == self.model:
                return None
        # Only return a name if related_name is explicitly set
        if self.related_name:
            return self.related_name
        return None

    def get_path_info(self, filtered_relation: Any = None) -> Any:
        if filtered_relation:
            return self.field.get_reverse_path_info(filtered_relation)
        else:
            return self.field.reverse_path_infos

    @cached_property
    def path_infos(self) -> Any:
        return self.get_path_info()

    def get_cache_name(self) -> str | None:
        """
        Return the name of the cache key to use for storing an instance of the
        forward model on the reverse model.
        """
        return self.get_accessor_name()


class ManyToOneRel(ForeignObjectRel):
    """
    Used by the ForeignKey field to store information about the relation.

    ``_model_meta.get_fields()`` returns this class to provide access to the field
    flags for the reverse relation.

    Note: Because we somewhat abuse the Rel objects by using them as reverse
    fields we get the funny situation where
    ``ManyToOneRel.many_to_one == False`` and
    ``ManyToOneRel.one_to_many == True``. This is unfortunate but the actual
    ManyToOneRel class is a private API and there is work underway to turn
    reverse relations into actual fields.
    """

    def __init__(
        self,
        field: Any,
        to: Any,
        related_name: str | None = None,
        related_query_name: str | None = None,
        limit_choices_to: Any = None,
        on_delete: Any = None,
    ):
        super().__init__(
            field,
            to,
            related_name=related_name,
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

    def get_related_field(self) -> Any:
        """
        Return the Field in the 'to' object to which this relationship is tied.
        """
        field = self.model._model_meta.get_field("id")
        if not field.concrete:
            raise FieldDoesNotExist("No related field named 'id'")
        return field

    def set_field_name(self) -> None:
        pass


class ManyToManyRel(ForeignObjectRel):
    """
    Used by ManyToManyField to store information about the relation.

    ``_model_meta.get_fields()`` returns this class to provide access to the field
    flags for the reverse relation.
    """

    def __init__(
        self,
        field: Any,
        to: Any,
        *,
        through: Any,
        through_fields: tuple[str, str] | None = None,
        related_name: str | None = None,
        related_query_name: str | None = None,
        limit_choices_to: Any = None,
        symmetrical: bool = True,
    ):
        super().__init__(
            field,
            to,
            related_name=related_name,
            related_query_name=related_query_name,
            limit_choices_to=limit_choices_to,
        )

        self.through = through
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

    def get_related_field(self) -> Any:
        """
        Return the field in the 'to' object to which this relationship is tied.
        Provided for symmetry with ManyToOneRel.
        """
        meta = self.through._model_meta
        if self.through_fields:
            field = meta.get_field(self.through_fields[0])
        else:
            for field in meta.fields:
                rel = getattr(field, "remote_field", None)
                if rel and rel.model == self.model:
                    break
        return field.foreign_related_fields[0]
