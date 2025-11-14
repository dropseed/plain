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
from plain.models.fields.related import ForeignKey, ManyToManyField

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
    "ForeignKey",
    "GenericIPAddressField",
    "IntegerField",
    "JSONField",
    "ManyToManyField",
    "PositiveBigIntegerField",
    "PositiveIntegerField",
    "PositiveSmallIntegerField",
    "PrimaryKeyField",
    "SmallIntegerField",
    "TextField",
    "TimeField",
    "URLField",
    "UUIDField",
]
