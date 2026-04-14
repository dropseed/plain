from .registry import models_registry, register_model  # noqa  Create the registry first
from . import (
    preflight,  # noqa  Imported for side effects (registers preflight checks)
)

# Imports that would create circular imports if sorted
from .base import Model
from .constraints import CheckConstraint, UniqueConstraint
from .db import get_connection
from .deletion import CASCADE, NO_ACTION, RESTRICT, SET_NULL
from .expressions import F
from .enums import IntegerChoices, TextChoices
from .fields import (
    BigIntegerField,
    BinaryField,
    BooleanField,
    DateField,
    DateTimeField,
    DecimalField,
    DurationField,
    EmailField,
    FloatField,
    GenericIPAddressField,
    IntegerField,
    PrimaryKeyField,
    SmallIntegerField,
    TextField,
    TimeField,
    URLField,
    UUIDField,
)
from .fields.json import JSONField
from .fields.timezones import TimeZoneField
from .fields.related import (
    ForeignKeyField,
    ManyToManyField,
)
from .fields.reverse_descriptors import (
    ReverseForeignKey,
    ReverseManyToMany,
)
from .indexes import Index
from .options import Options
from .query import QuerySet
from .query_utils import Q
from . import types

# This module exports the user-facing API for defining model classes,
# with a secondary focus on the most common query utilities like Q.
# Advanced query-time features (aggregates, expressions, etc.) should be
# imported from their specific modules (e.g., plain.postgres.aggregates).
__all__ = [
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
    "DateField",
    "DateTimeField",
    "DecimalField",
    "DurationField",
    "EmailField",
    "FloatField",
    "GenericIPAddressField",
    "IntegerField",
    "PrimaryKeyField",
    "SmallIntegerField",
    "TextField",
    "TimeField",
    "URLField",
    "UUIDField",
    # From fields.json
    "JSONField",
    # From fields.timezones
    "TimeZoneField",
    # From indexes
    "Index",
    # From deletion
    "CASCADE",
    "NO_ACTION",
    "RESTRICT",
    "SET_NULL",
    # From options
    "Options",
    # From query
    "QuerySet",
    # From query_utils
    "Q",
    # From expressions
    "F",
    # From base
    "Model",
    # From fields.related
    "ForeignKeyField",
    "ManyToManyField",
    # From fields.reverse_descriptors
    "ReverseForeignKey",
    "ReverseManyToMany",
    # From db
    "get_connection",
    # From registry
    "register_model",
    "models_registry",
    # Typed field imports
    "types",
]
