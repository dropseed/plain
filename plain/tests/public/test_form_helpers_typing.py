"""Pin the type-narrowing contract of `field_value`/`field_errors`.

The whole point of the helpers is typing-by-default: `field_value(form,
ContactForm.email)` narrows to `str | None`, not `Any`. `assert_type` is
the static check — a regression that collapses the return type back to
`Any` (or anything else) is caught by `ty` when `./scripts/fix --check`
runs over the test suite. At runtime, `assert_type` is a no-op.
"""

from __future__ import annotations

from datetime import date
from typing import Any, assert_type

from plain.forms import Error, Form, Invalid, field_errors, field_value, types


class TypingForm(Form):
    name = types.TextField()
    email = types.EmailField()
    age = types.IntegerField(required=False)
    when = types.DateField(required=False)
    subscribe = types.BooleanField(required=False)


# A Form|Invalid value is what gets passed to the template — the helpers
# accept either arm of the union without narrowing first.
form: Form | Invalid = TypingForm.validate({"name": "Dave", "email": "dave@x.com"})


def test_field_value_narrows_through_field_T():
    """`field_value(form, Field[T])` returns `T | None`. The `T` is the
    cleaned-value type carried by the field reference."""
    assert_type(field_value(form, TypingForm.name), str | None)
    assert_type(field_value(form, TypingForm.email), str | None)
    assert_type(field_value(form, TypingForm.age), int | None)
    assert_type(field_value(form, TypingForm.when), date | None)
    assert_type(field_value(form, TypingForm.subscribe), bool | None)


def test_field_errors_returns_list_of_errors():
    """`field_errors` doesn't carry per-field typing — errors are uniform."""
    assert_type(field_errors(form, TypingForm.email), list[Error])


def test_field_reference_is_typed_at_class_access():
    """`TypingForm.email` resolves to the field reference (typed), not the
    cleaned value. The cleaned value comes from instance access via the
    descriptor's other overload."""
    # Class access — the typed Field reference rides through type checking.
    assert_type(TypingForm.email.name, str)
    assert_type(TypingForm.email.required, bool)
    assert_type(TypingForm.email.html_id, str)


def test_cleaned_attribute_access_narrows_to_T():
    """`result.email` on a validated Form instance is `T` — the cleaned
    value type, not the field reference."""
    result = TypingForm.validate({"name": "Dave", "email": "dave@x.com"})
    if not result:
        return
    # Past the `if not result:` guard the union narrows to TypingForm.
    assert_type(result.name, str)
    assert_type(result.email, str)
    assert_type(result.age, int | None)


def test_form_or_invalid_narrows_via_isinstance():
    """`isinstance(result, Invalid)` narrows the union arm — the `Invalid`
    side carries `.errors: list[Error]` and `.raw: dict[str, Any]`."""
    result = TypingForm.validate({})
    if isinstance(result, Invalid):
        assert_type(result.errors, list[Error])
        assert_type(result.raw, dict[str, Any])
