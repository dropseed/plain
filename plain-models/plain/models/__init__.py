from .registry import models_registry, register_model  # noqa  Create the registry first
from . import (
    preflight,  # noqa  Imported for side effects (registers preflight checks)
)

# Imports that would create circular imports if sorted
from .base import Model
from .constraints import CheckConstraint, UniqueConstraint
from .db import IntegrityError, db_connection
from .deletion import CASCADE, DO_NOTHING, PROTECT, RESTRICT, SET, SET_DEFAULT, SET_NULL
from .enums import IntegerChoices, TextChoices
from .fields import (
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
from .fields.json import JSONField
from .fields.related import (
    ForeignKey,
    ManyToManyField,
)
from .indexes import Index
from .options import Options
from .query import QuerySet
from .query_utils import Q

# This module exports the user-facing API for defining model classes,
# with a secondary focus on the most common query utilities like Q.
# Advanced query-time features (aggregates, expressions, etc.) should be
# imported from their specific modules (e.g., plain.models.aggregates).
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
