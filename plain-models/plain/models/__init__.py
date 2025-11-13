from __future__ import annotations

from typing import TYPE_CHECKING, Any, TypeVar

from .registry import models_registry, register_model  # isort:skip  Create the registry first
from . import (
    preflight,  # noqa  Imported for side effects (registers preflight checks)
)

# Imports that would create circular imports if sorted
from .base import Model
from .constraints import CheckConstraint, UniqueConstraint
from .db import IntegrityError, db_connection
from .deletion import CASCADE, DO_NOTHING, PROTECT, RESTRICT, SET, SET_DEFAULT, SET_NULL
from .enums import IntegerChoices, TextChoices
from .fields.core import (
    NOT_PROVIDED,
    BigIntegerField,
    BinaryField,
    BooleanField,
    CharField,
    DateField,
    DateTimeField,
    DecimalField,
    DurationField,
    EmailField,
    FloatField,
    GenericIPAddressField,
    IntegerField,
    JSONField,
    PositiveBigIntegerField,
    PositiveIntegerField,
    PositiveSmallIntegerField,
    PrimaryKeyField,
    SmallIntegerField,
    TextField,
    TimeField,
    URLField,
    UUIDField,
)
from .fields.related import ForeignKey, ManyToManyField
from .indexes import Index
from .options import Options
from .query import QuerySet
from .query_utils import Q

# Type variable for Field generic
_T = TypeVar("_T")

if TYPE_CHECKING:
    # For type checkers: Field[T] is just T
    # This makes `name: Field[str] = CharField()` type-check correctly
    # because the annotation resolves to `str`, not `Field[str]`
    Field = _T  # type: ignore[misc, valid-type]
else:
    # At runtime: Field is a marker class for the metaclass to detect
    class Field:  # type: ignore[no-redef]
        """
        Generic type marker for model field annotations.

        This allows for cleaner type annotations in model definitions:

            class User(Model):
                email: Field[str] = EmailField()
                age: Field[int] = IntegerField(default=0)

        The Field[T] annotation tells type checkers what type the field will
        return when accessed on model instances, while the actual field instance
        (EmailField(), etc.) provides the database column configuration.
        """

        def __class_getitem__(cls, item: Any) -> Any:
            # Return a marker that the metaclass can detect
            # This is what gets used at runtime in annotations
            return _FieldMarker(item)


class _FieldMarker:
    """Runtime marker for Field[T] annotations."""

    __slots__ = ("type_arg",)

    def __init__(self, type_arg: Any) -> None:
        self.type_arg = type_arg


# This module exports the user-facing API for defining model classes,
# with a secondary focus on the most common query utilities like Q.
# Advanced query-time features (aggregates, expressions, etc.) should be
# imported from their specific modules (e.g., plain.models.aggregates).
__all__ = [
    # Typing
    "Field",
    "NOT_PROVIDED",
    # From constraints
    "CheckConstraint",
    "UniqueConstraint",
    # From enums
    "IntegerChoices",
    "TextChoices",
    # From fields
    "BigIntegerField",
    "BinaryField",
    "BooleanField",
    "CharField",
    "DateField",
    "DateTimeField",
    "DecimalField",
    "DurationField",
    "EmailField",
    "FloatField",
    "GenericIPAddressField",
    "IntegerField",
    "PositiveBigIntegerField",
    "PositiveIntegerField",
    "PositiveSmallIntegerField",
    "PrimaryKeyField",
    "SmallIntegerField",
    "TextField",
    "TimeField",
    "URLField",
    "UUIDField",
    # From fields.json
    "JSONField",
    # From indexes
    "Index",
    # From deletion
    "CASCADE",
    "DO_NOTHING",
    "PROTECT",
    "RESTRICT",
    "SET",
    "SET_DEFAULT",
    "SET_NULL",
    # From options
    "Options",
    # From query
    "QuerySet",
    # From query_utils
    "Q",
    # From base
    "Model",
    # From fields.related
    "ForeignKey",
    "ManyToManyField",
    # From db
    "db_connection",
    "IntegrityError",
    # From registry
    "register_model",
    "models_registry",
]
