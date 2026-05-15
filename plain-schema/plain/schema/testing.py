"""Hypothesis strategy for `Schema` classes — generate valid input dicts
that exercise field constraints during property tests.

This is an optional integration. `hypothesis` is not a Plain dependency;
import this module only in test code, after installing hypothesis as a
dev dependency.

Usage:

    from hypothesis import given
    from plain.schema.testing import schema_strategy

    @given(payload=schema_strategy(MySchema))
    def test_view_handles_any_valid_payload(client, payload):
        response = client.post("/api/things/", data=payload)
        assert response.status_code == 201

The strategy walks the schema's declared fields and produces a hypothesis
strategy per field, returning a `dict[str, Any]` that `MySchema.validate()`
accepts. Optional fields randomly include or omit the value.

Field-type coverage:
  - TextField, EmailField, URLField, RegexField (regex pattern → from_regex)
  - IntegerField, FloatField, DecimalField
  - BooleanField, NullBooleanField
  - ChoiceField, MultipleChoiceField, TypedChoiceField
  - DateField, DateTimeField, TimeField, DurationField
  - UUIDField

Unsupported (raises): FileField, ImageField, JSONField — open-ended
shapes that don't have an obvious uniform strategy. If you need them,
build a custom strategy for that field and merge with the rest.
"""

from __future__ import annotations

import string
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Any

from hypothesis import strategies as st

from plain.forms import fields as form_fields

from .schema import Schema

__all__ = ("schema_strategy", "field_strategy")


def field_strategy(field: form_fields.Field) -> st.SearchStrategy[Any]:
    """Strategy for a single field's *value* (not wrapped in a dict).

    `required=False` is handled by `schema_strategy()`, which adds the
    `none()` branch and decides whether to include the key at all.
    """
    # isinstance checks run subclass-before-base: RegexField before
    # EmailField/URLField, MultipleChoiceField before ChoiceField,
    # NullBooleanField before BooleanField.
    if isinstance(field, form_fields.RegexField):
        regex = getattr(field, "regex", None)
        pattern = getattr(regex, "pattern", None) if regex is not None else None
        if isinstance(pattern, str):
            return st.from_regex(pattern, fullmatch=True)
        # Fall through to TextField behavior

    if isinstance(field, form_fields.EmailField):
        return st.emails()

    if isinstance(field, form_fields.URLField):
        return st.from_regex(
            r"^https?://[a-z][a-z0-9.-]{0,32}\.test(/[a-zA-Z0-9._-]{0,16})?$",
            fullmatch=True,
        )

    if isinstance(field, form_fields.UUIDField):
        return st.uuids().map(str)

    if isinstance(field, form_fields.MultipleChoiceField):
        choices = getattr(field, "choices", None) or []
        values = [v for v, _ in choices]
        if not values:
            return st.lists(st.text(), min_size=0, max_size=3)
        return st.lists(st.sampled_from(values), min_size=0, max_size=len(values))

    if isinstance(field, form_fields.ChoiceField):
        choices = getattr(field, "choices", None) or []
        values = [v for v, _ in choices]
        if not values:
            return st.text(min_size=1, max_size=20)
        return st.sampled_from(values)

    if isinstance(field, form_fields.TextField):
        min_length = getattr(field, "min_length", None) or 0
        max_length = getattr(field, "max_length", None) or 100
        # TextField strips by default — generate without leading/trailing
        # whitespace so post-strip length still satisfies min_length.
        return st.text(
            alphabet=string.ascii_letters + string.digits,
            min_size=min_length,
            max_size=max_length,
        )

    if isinstance(field, form_fields.IntegerField):
        return st.integers(
            min_value=getattr(field, "min_value", None),
            max_value=getattr(field, "max_value", None),
        )

    if isinstance(field, form_fields.FloatField):
        return st.floats(
            min_value=getattr(field, "min_value", None),
            max_value=getattr(field, "max_value", None),
            allow_nan=False,
            allow_infinity=False,
        )

    if isinstance(field, form_fields.DecimalField):
        max_digits = getattr(field, "max_digits", None) or 10
        decimal_places = getattr(field, "decimal_places", None) or 2
        # Generate ints in the integer-part range, divide for places.
        max_int = 10 ** (max_digits - decimal_places) - 1
        return st.decimals(
            min_value=Decimal(-max_int),
            max_value=Decimal(max_int),
            places=decimal_places,
            allow_nan=False,
            allow_infinity=False,
        )

    if isinstance(field, form_fields.NullBooleanField):
        return st.one_of(st.booleans(), st.none())

    if isinstance(field, form_fields.BooleanField):
        # BooleanField(required=True) means "must be checked" — Plain treats
        # `False` as a missing-value (matches HTML checkbox semantics where
        # unchecked sends no key). For required fields, only True passes
        # validation; for optional fields either value is fine.
        if field.required:
            return st.just(True)
        return st.booleans()

    if isinstance(field, form_fields.DateTimeField):
        return st.datetimes().map(datetime.isoformat)

    if isinstance(field, form_fields.DateField):
        return st.dates().map(date.isoformat)

    if isinstance(field, form_fields.TimeField):
        return st.times().map(time.isoformat)

    if isinstance(field, form_fields.DurationField):
        return st.timedeltas(
            min_value=timedelta(0),
            max_value=timedelta(days=365),
        ).map(str)

    raise NotImplementedError(
        f"No hypothesis strategy for {type(field).__name__}. "
        f"FileField/ImageField/JSONField are open-ended; build a custom "
        f"strategy for those fields and merge with the schema's other fields."
    )


def schema_strategy(
    schema_class: type[Schema],
) -> st.SearchStrategy[dict[str, Any]]:
    """Hypothesis strategy returning input dicts that
    `schema_class.validate()` accepts.

    Optional fields (`required=False`) are randomly omitted. Required
    fields are always present with a generated value.
    """
    field_strategies: dict[str, st.SearchStrategy[Any]] = {}
    optional_field_names: list[str] = []
    for name, field in schema_class._schema_fields.items():
        field_strategies[name] = field_strategy(field)
        if not field.required:
            optional_field_names.append(name)

    @st.composite
    def build(draw: st.DrawFn) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for name, strategy in field_strategies.items():
            if name in optional_field_names and draw(st.booleans()):
                continue
            out[name] = draw(strategy)
        return out

    return build()
