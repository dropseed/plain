from __future__ import annotations

import datetime
import re
from collections import namedtuple
from collections.abc import Generator
from typing import TYPE_CHECKING, Any

from plain.models.fields.related import RECURSIVE_RELATIONSHIP_CONSTANT

if TYPE_CHECKING:
    from plain.models.fields import Field

FieldReference = namedtuple("FieldReference", "to through")

COMPILED_REGEX_TYPE = type(re.compile(""))


class RegexObject:
    def __init__(self, obj: Any) -> None:
        self.pattern = obj.pattern
        self.flags = obj.flags

    def __eq__(self, other: Any) -> bool:
        if not isinstance(other, RegexObject):
            return NotImplemented
        return self.pattern == other.pattern and self.flags == other.flags


def get_migration_name_timestamp() -> str:
    return datetime.datetime.now().strftime("%Y%m%d_%H%M")


def resolve_relation(
    model: str | Any, package_label: str | None = None, model_name: str | None = None
) -> tuple[str, str]:
    """
    Turn a model class or model reference string and return a model tuple.

    package_label and model_name are used to resolve the scope of recursive and
    unscoped model relationship.
    """
    if isinstance(model, str):
        if model == RECURSIVE_RELATIONSHIP_CONSTANT:
            if package_label is None or model_name is None:
                raise TypeError(
                    "package_label and model_name must be provided to resolve "
                    "recursive relationships."
                )
            return package_label, model_name
        if "." in model:
            package_label, model_name = model.split(".", 1)
            return package_label, model_name.lower()
        if package_label is None:
            raise TypeError(
                "package_label must be provided to resolve unscoped model relationships."
            )
        return package_label, model.lower()
    return model.model_options.package_label, model.model_options.model_name


def field_references(
    model_tuple: tuple[str, str],
    field: Field,
    reference_model_tuple: tuple[str, str],
    reference_field_name: str | None = None,
    reference_field: Field | None = None,
) -> FieldReference | bool:
    """
    Return either False or a FieldReference if `field` references provided
    context.

    False positives can be returned if `reference_field_name` is provided
    without `reference_field` because of the introspection limitation it
    incurs. This should not be an issue when this function is used to determine
    whether or not an optimization can take place.
    """
    remote_field = field.remote_field
    if not remote_field:
        return False
    references_to = None
    references_through = None
    if resolve_relation(remote_field.model, *model_tuple) == reference_model_tuple:
        # ForeignObject always references 'id'
        if (
            reference_field_name is None
            or reference_field_name == "id"
            or (reference_field is None or reference_field.primary_key)
        ):
            references_to = (remote_field, ["id"])
    through = getattr(remote_field, "through", None)
    if through and resolve_relation(through, *model_tuple) == reference_model_tuple:
        through_fields = getattr(remote_field, "through_fields", None)
        if (
            reference_field_name is None
            or
            # Unspecified through_fields.
            through_fields is None
            or
            # Reference to field.
            reference_field_name in through_fields
        ):
            references_through = (remote_field, through_fields)
    if not (references_to or references_through):
        return False
    return FieldReference(references_to, references_through)


def get_references(
    state: Any, model_tuple: tuple[str, str], field_tuple: tuple[Any, ...] = ()
) -> Generator[tuple[Any, str, Field, FieldReference], None, None]:
    """
    Generator of (model_state, name, field, reference) referencing
    provided context.

    If field_tuple is provided only references to this particular field of
    model_tuple will be generated.
    """
    for state_model_tuple, model_state in state.models.items():
        for name, field in model_state.fields.items():
            reference = field_references(
                state_model_tuple,
                field,
                model_tuple,
                *field_tuple,  # type: ignore[arg-type]
            )
            if reference:
                yield model_state, name, field, reference


def field_is_referenced(
    state: Any, model_tuple: tuple[str, str], field_tuple: tuple[Any, ...]
) -> bool:
    """Return whether `field_tuple` is referenced by any state models."""
    return next(get_references(state, model_tuple, field_tuple), None) is not None
