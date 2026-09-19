from __future__ import annotations

from plain.postgres import Field, types

from plain import postgres


@postgres.register_model
class StringConditionsExample(postgres.Model):
    """String-valued fields that are *not* TextField subclasses.

    `Field` declares the pattern conditions for every string-valued field, so
    these have to carry them at runtime too — `GenericIPAddressField` is a
    DefaultableField and `RandomStringField` is a ColumnField, and neither
    inherits TextField's implementations.
    """

    label: Field[str] = types.TextField(max_length=50)
    ip: Field[str] = types.GenericIPAddressField()
    token: Field[str] = types.RandomStringField(length=16)
