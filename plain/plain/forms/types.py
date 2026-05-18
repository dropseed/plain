"""Typed field re-exports for form declarations.

The companion `.pyi` stub tells type checkers that each field constructor
returns a typed `Field[T]`, enabling typed form definitions like:

    from plain.forms import Form, types

    class ContactForm(Form):
        email = types.EmailField()
        age = types.IntegerField()

At runtime these are Field instances; the type checker sees `Field[T]`. This
mirrors the `from plain.postgres import types` pattern used by models.
"""

from __future__ import annotations

from .fields import (
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
