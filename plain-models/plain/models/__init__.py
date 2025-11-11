from typing import TYPE_CHECKING

from . import (
    preflight,  # noqa
)
from .aggregates import *  # NOQA
from .aggregates import __all__ as aggregates_all
from .constraints import *  # NOQA
from .constraints import __all__ as constraints_all
from .db import (
    PLAIN_VERSION_PICKLE_KEY,
    DatabaseError,
    DataError,
    Error,
    IntegrityError,
    InterfaceError,
    InternalError,
    NotSupportedError,
    OperationalError,
    ProgrammingError,
    close_old_connections,
    db_connection,
    reset_queries,
)
from .deletion import (
    CASCADE,
    DO_NOTHING,
    PROTECT,
    RESTRICT,
    SET,
    SET_DEFAULT,
    SET_NULL,
    ProtectedError,
    RestrictedError,
)
from .enums import *  # NOQA
from .enums import __all__ as enums_all
from .expressions import (
    Case,
    Exists,
    Expression,
    ExpressionList,
    ExpressionWrapper,
    F,
    Func,
    OrderBy,
    OuterRef,
    RowRange,
    Subquery,
    Value,
    ValueRange,
    When,
    Window,
    WindowFrame,
)

# Always import Field and NOT_PROVIDED as they're needed for isinstance checks
# and type annotations, regardless of TYPE_CHECKING
from .fields import NOT_PROVIDED, Field  # noqa: F401

# Field imports: use type stubs during type checking, real classes at runtime
if TYPE_CHECKING:
    # Import type stub overrides that make fields appear to return value types
    # Import non-field items from real implementation
    from .fields import BLANK_CHOICE_DASH, Empty
    from .fields.typing import (
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
        ForeignKey,
        GenericIPAddressField,
        IntegerField,
        JSONField,
        ManyToManyField,
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
else:
    # Import real field classes at runtime
    from .fields import (
        BLANK_CHOICE_DASH,
        BigIntegerField,
        BinaryField,
        BooleanField,
        CharField,
        DateField,
        DateTimeField,
        DecimalField,
        DurationField,
        EmailField,
        Empty,
        FloatField,
        ForeignKey,
        GenericIPAddressField,
        IntegerField,
        JSONField,
        ManyToManyField,
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

from .indexes import *  # NOQA
from .indexes import __all__ as indexes_all
from .lookups import Lookup, Transform
from .query import Prefetch, QuerySet, prefetch_related_objects
from .query_utils import FilteredRelation, Q
from .registry import models_registry, register_model

# Imports that would create circular imports if sorted
from .base import DEFERRED, Model  # isort:skip
from .options import Options  # isort:skip
from .fields.reverse_related import (  # isort:skip
    ForeignObjectRel,
    ManyToOneRel,
    ManyToManyRel,
)

# Register the json field lookup transforms
from .fields import json  # isort:skip, # noqa: F401


__all__ = aggregates_all + constraints_all + enums_all + indexes_all
__all__ += [
    # Field base classes and sentinels
    "Field",
    "NOT_PROVIDED",
    # Field constructors (explicitly imported for runtime/TYPE_CHECKING handling)
    "BLANK_CHOICE_DASH",
    "BigIntegerField",
    "BinaryField",
    "BooleanField",
    "CharField",
    "DateField",
    "DateTimeField",
    "DecimalField",
    "DurationField",
    "EmailField",
    "Empty",
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
    # Deletion behaviors
    "CASCADE",
    "DO_NOTHING",
    "PROTECT",
    "RESTRICT",
    "SET",
    "SET_DEFAULT",
    "SET_NULL",
    "ProtectedError",
    "RestrictedError",
    # Expressions and lookups
    "Case",
    "Exists",
    "Expression",
    "ExpressionList",
    "ExpressionWrapper",
    "F",
    "Func",
    "OrderBy",
    "OuterRef",
    "RowRange",
    "Subquery",
    "Value",
    "ValueRange",
    "When",
    "Window",
    "WindowFrame",
    "JSONField",
    "Lookup",
    "Transform",
    # Model and query utilities
    "Options",
    "Prefetch",
    "Q",
    "QuerySet",
    "prefetch_related_objects",
    "DEFERRED",
    "Model",
    "FilteredRelation",
    # Related fields
    "ForeignKey",
    "ManyToManyField",
    "ForeignObjectRel",
    "ManyToOneRel",
    "ManyToManyRel",
]

# DB-related exports
__all__ += [
    "db_connection",
    "reset_queries",
    "close_old_connections",
    "DatabaseError",
    "IntegrityError",
    "InternalError",
    "ProgrammingError",
    "DataError",
    "NotSupportedError",
    "Error",
    "InterfaceError",
    "OperationalError",
    "PLAIN_VERSION_PICKLE_KEY",
]

# Registry exports
__all__ += ["register_model", "models_registry"]
