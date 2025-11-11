"""Plain models fields module.

This module exports all field types from their respective modules:
- Core fields (including JSONField) from .core - imported eagerly
- Related fields from .related - lazy loaded to avoid circular imports

JSONField is eagerly imported (moved to core.py). Related fields must be lazy-loaded
because they create unavoidable circular dependencies through query/sql modules.

Optimizations made to reduce circular imports:
1. expressions.py imports directly from fields.core
2. query.py imports directly from fields.core
3. sql.query.py uses function-scope import for Count

JSON field transforms and lookups are in .json and loaded via models.__init__
after all modules are initialized.
"""

# Import all core fields eagerly
from .core import (
    BLANK_CHOICE_DASH,
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
    Empty,
    Field,
    FloatField,
    GenericIPAddressField,
    IntegerField,
    JSONField,
    PositiveBigIntegerField,
    PositiveIntegerField,
    PositiveIntegerRelDbTypeMixin,
    PositiveSmallIntegerField,
    PrimaryKeyField,
    SmallIntegerField,
    TextField,
    TimeField,
    URLField,
    UUIDField,
)

# Note: ForeignKey, ManyToManyField are NOT imported eagerly to avoid circular imports.
# They are available via lazy import through __getattr__ below.


def __getattr__(name: str):
    """Lazy import for related fields to avoid circular imports."""
    if name in ("ForeignKey", "ManyToManyField"):
        from .related import ForeignKey, ManyToManyField

        if name == "ForeignKey":
            return ForeignKey
        else:
            return ManyToManyField
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    # Core field types
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
    "Field",
    "FloatField",
    "GenericIPAddressField",
    "IntegerField",
    "NOT_PROVIDED",
    "PositiveBigIntegerField",
    "PositiveIntegerField",
    "PositiveIntegerRelDbTypeMixin",
    "PositiveSmallIntegerField",
    "PrimaryKeyField",
    "SmallIntegerField",
    "TextField",
    "TimeField",
    "URLField",
    "UUIDField",
    # JSON field
    "JSONField",
    # Related fields (available via lazy __getattr__)
    "ForeignKey",
    "ManyToManyField",
]
