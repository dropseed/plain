"""Typed field re-exports for schema declarations.

The companion `.pyi` stub tells type checkers that field constructors return
primitive Python types, enabling typed schema definitions like:

    from plain.schema import Schema, types

    class ContactSchema(Schema):
        email: str = types.EmailField()
        age: int = types.IntegerField()

At runtime these are Field instances; the type checker sees the primitives.
This mirrors the `from plain.postgres import types` pattern used by models.
"""

from __future__ import annotations

from plain.forms.fields import (
    BooleanField,
    ChoiceField,
    DateField,
    DateTimeField,
    DecimalField,
    DurationField,
    EmailField,
    FileField,
    FloatField,
    ImageField,
    IntegerField,
    JSONField,
    MultipleChoiceField,
    NullBooleanField,
    RegexField,
    TextField,
    TimeField,
    TypedChoiceField,
    URLField,
    UUIDField,
)

__all__ = (
    "BooleanField",
    "ChoiceField",
    "DateField",
    "DateTimeField",
    "DecimalField",
    "DurationField",
    "EmailField",
    "FileField",
    "FloatField",
    "ImageField",
    "IntegerField",
    "JSONField",
    "MultipleChoiceField",
    "NullBooleanField",
    "RegexField",
    "TextField",
    "TimeField",
    "TypedChoiceField",
    "URLField",
    "UUIDField",
)
