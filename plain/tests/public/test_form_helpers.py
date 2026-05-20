"""Public contract — `field_value`, `field_errors`, and `form_errors`.

A view passes the `Form | Invalid` straight to the template; the template
reads each field through these helpers. Each takes a field reference
(`ProfileForm.email`) so the cleaned-value type rides through `Field[T]`.
"""

from __future__ import annotations

import pytest

from plain.forms import (
    Form,
    Invalid,
    field_errors,
    field_value,
    form_errors,
    types,
)
from plain.utils.datastructures import MultiValueDict


class ProfileForm(Form):
    name = types.TextField()
    email = types.EmailField()
    bio = types.TextField(required=False)


class TestFieldValueOnSuccess:
    def test_returns_cleaned_value(self):
        form = ProfileForm.validate(
            {"name": "Dave", "email": "dave@x.com", "bio": "hi"}
        )
        assert form
        assert field_value(form, ProfileForm.name) == "Dave"
        assert field_value(form, ProfileForm.email) == "dave@x.com"
        assert field_value(form, ProfileForm.bio) == "hi"

    def test_returns_empty_string_for_absent_optional_text(self):
        # TextField cleans missing input to "" (a TextField that's required=False
        # accepts the empty input). The helper returns the cleaned value as-is.
        form = ProfileForm.validate({"name": "Dave", "email": "dave@x.com"})
        assert form
        assert field_value(form, ProfileForm.bio) == ""

    def test_returns_none_for_unset_attribute(self):
        # A directly-constructed Form with no value for a field
        form = ProfileForm()
        assert field_value(form, ProfileForm.name) is None


class TestFieldValueOnFailure:
    def test_returns_raw_input_for_redisplay(self):
        invalid = ProfileForm.validate({"name": "", "email": "not-an-email"})
        assert not invalid
        assert isinstance(invalid, Invalid)
        # Raw input comes back so the user sees what they typed
        assert field_value(invalid, ProfileForm.email) == "not-an-email"

    def test_returns_none_when_raw_missing(self):
        invalid = ProfileForm.validate({"email": "not-an-email"})
        assert not invalid
        assert isinstance(invalid, Invalid)
        assert field_value(invalid, ProfileForm.name) is None

    def test_multi_value_field_returns_list(self):
        class Picker(Form):
            tags = types.MultipleChoiceField(choices=[("a", "A"), ("b", "B")])

        raw = MultiValueDict({"tags": ["a", "b"]})
        invalid = Picker.validate(raw)
        # MultiValueDict's getlist surfaces both values
        assert isinstance(invalid, Form)  # validates fine — testing the helper
        assert field_value(invalid, Picker.tags) == ["a", "b"]


class TestFieldErrors:
    def test_empty_on_success(self):
        form = ProfileForm.validate(
            {"name": "Dave", "email": "dave@x.com", "bio": "hi"}
        )
        assert form
        assert field_errors(form, ProfileForm.name) == []

    def test_returns_field_errors_on_failure(self):
        invalid = ProfileForm.validate({"name": "Dave", "email": "bad"})
        assert not invalid
        assert isinstance(invalid, Invalid)
        errs = field_errors(invalid, ProfileForm.email)
        assert len(errs) >= 1
        assert all(e.field == "email" for e in errs)

    def test_does_not_include_other_fields_errors(self):
        invalid = ProfileForm.validate({})  # both name and email fail
        assert not invalid
        assert isinstance(invalid, Invalid)
        name_errs = field_errors(invalid, ProfileForm.name)
        assert all(e.field == "name" for e in name_errs)


class TestFormErrors:
    def test_empty_on_success(self):
        form = ProfileForm.validate(
            {"name": "Dave", "email": "dave@x.com", "bio": "hi"}
        )
        assert form
        assert form_errors(form) == []

    def test_empty_on_field_only_failure(self):
        invalid = ProfileForm.validate({"email": "bad"})
        assert not invalid
        # All errors are attached to fields — none are form-level
        assert form_errors(invalid) == []

    def test_returns_form_level_errors_from_check(self):
        class Strict(Form):
            password = types.TextField()
            confirm = types.TextField()

            def check(self):
                from plain.forms import Error

                if self.password != self.confirm:
                    return [
                        Error(
                            "Passwords don't match.",
                            "mismatch",
                            field=None,
                        )
                    ]
                return None

        invalid = Strict.validate({"password": "a", "confirm": "b"})
        assert not invalid
        errs = form_errors(invalid)
        assert len(errs) == 1
        assert errs[0].code == "mismatch"
        assert errs[0].field is None


class TestFieldMetadata:
    """Field metadata isn't a helper — it lives on the Field reference."""

    def test_required_from_field(self):
        assert ProfileForm.email.required is True
        assert ProfileForm.bio.required is False

    def test_name_from_field(self):
        assert ProfileForm.email.name == "email"

    def test_html_id_from_field(self):
        assert ProfileForm.email.html_id == "id_email"

    def test_choices_from_field(self):
        class Picker(Form):
            color = types.ChoiceField(choices=[("r", "Red"), ("g", "Green")])

        assert Picker.color.choices == [("r", "Red"), ("g", "Green")]


class TestErrorMessageBoundary:
    """Helpers don't try to validate that errors reference real fields —
    that's a render concern that templates handle naturally (no entry
    for an unknown field). Test that handing in nonsense doesn't crash."""

    def test_field_for_a_form_not_used_returns_empty(self):
        class Other(Form):
            something = types.TextField()

        invalid = ProfileForm.validate({"email": "bad"})
        assert not invalid
        # Asking for errors on a field that isn't part of this form is empty
        assert field_errors(invalid, Other.something) == []


if __name__ == "__main__":
    pytest.main([__file__])
