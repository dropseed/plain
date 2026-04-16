"""
Typed field imports for better IDE and type checker support.

This module provides the same field classes as plain.postgres.fields,
but with a companion .pyi stub file that makes type checkers interpret
field assignments as their primitive Python types.

Usage:
    from plain.postgres import types

    @postgres.register_model
    class User(postgres.Model):
        email: str = types.EmailField()
        age: int = types.IntegerField()
        is_active: bool = types.BooleanField(default=True)

This is optional - you can continue using untyped field definitions.
"""

# Re-export scalar field types
from plain.postgres.fields import (
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
from plain.postgres.fields.encrypted import (
    EncryptedJSONField,
    EncryptedTextField,
)
from plain.postgres.fields.json import JSONField
from plain.postgres.fields.related import ForeignKeyField, ManyToManyField
from plain.postgres.fields.related_managers import (
    ManyToManyManager,
    ReverseForeignKeyManager,
)
from plain.postgres.fields.reverse_descriptors import (
    ReverseForeignKey,
    ReverseManyToMany,
)
from plain.postgres.fields.timezones import TimeZoneField

__all__ = [
    "BigIntegerField",
    "BinaryField",
    "BooleanField",
    "DateField",
    "DateTimeField",
    "DecimalField",
    "DurationField",
    "EmailField",
    "EncryptedJSONField",
    "EncryptedTextField",
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
    "PrimaryKeyField",
    "RandomStringField",
    "SmallIntegerField",
    "TextField",
    "TimeField",
    "TimeZoneField",
    "URLField",
    "UUIDField",
]
