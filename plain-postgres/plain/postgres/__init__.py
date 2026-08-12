from importlib.metadata import version

__version__ = version("plain.postgres")

from .registry import models_registry, register_model  # noqa  Create the registry first
from . import (
    preflight,  # noqa  Imported for side effects (registers preflight checks)
)

# Imports that would create circular imports if sorted
from .base import Model
from .constraints import CheckConstraint, UniqueConstraint
from .db import get_connection, use_management_connection
from .middleware import DatabaseConnectionMiddleware
from .deletion import CASCADE, NO_ACTION, RESTRICT, SET_NULL
from .expressions import F
from .enums import TextChoices
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
    RandomStringField,
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
    "CASCADE",
    "NO_ACTION",
    "RESTRICT",
    "SET_NULL",
    "BigIntegerField",
    "BinaryField",
    "BooleanField",
    "CheckConstraint",
    "DatabaseConnectionMiddleware",
    "DateField",
    "DateTimeField",
    "DecimalField",
    "DurationField",
    "EmailField",
    "F",
    "FloatField",
    "ForeignKeyField",
    "GenericIPAddressField",
    "Index",
    "IntegerField",
    "JSONField",
    "ManyToManyField",
    "Model",
    "Options",
    "PrimaryKeyField",
    "Q",
    "QuerySet",
    "RandomStringField",
    "ReverseForeignKey",
    "ReverseManyToMany",
    "SmallIntegerField",
    "TextChoices",
    "TextField",
    "TimeField",
    "TimeZoneField",
    "URLField",
    "UUIDField",
    "UniqueConstraint",
    "get_connection",
    "models_registry",
    "register_model",
    "types",
    "use_management_connection",
]
