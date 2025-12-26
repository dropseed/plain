"""
Typed field imports for better IDE and type checker support.

This module provides the same field classes as plain.models.fields,
but with a companion .pyi stub file that makes type checkers interpret
field assignments as their primitive Python types.

Usage:
    from plain.models import types

    @models.register_model
    class User(models.Model):
        email: str = types.EmailField()
        age: int = types.IntegerField()
        is_active: bool = types.BooleanField(default=True)

This is optional - you can continue using untyped field definitions.
"""

# Re-export scalar field types
from plain.models.fields import (
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
from plain.models.fields.json import JSONField
from plain.models.fields.related import ForeignKeyField, ManyToManyField
from plain.models.fields.related_managers import (
    ManyToManyManager,
    ReverseForeignKeyManager,
)
from plain.models.fields.reverse_descriptors import (
    ReverseForeignKey,
    ReverseManyToMany,
)
from plain.models.fields.timezones import TimeZoneField

__all__ = [
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
    "ForeignKeyField",
    "GenericIPAddressField",
    "IntegerField",
    "JSONField",
    "ManyToManyField",
    "ManyToManyManager",
    "ReverseForeignKey",
    "ReverseForeignKeyManager",
    "ReverseManyToMany",
    "PositiveBigIntegerField",
    "PositiveIntegerField",
    "PositiveSmallIntegerField",
    "PrimaryKeyField",
    "SmallIntegerField",
    "TextField",
    "TimeField",
    "TimeZoneField",
    "URLField",
    "UUIDField",
]
