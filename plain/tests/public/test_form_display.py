"""Public contract — `FormDisplay`, the render-time adapter.

A view wraps a validation outcome in a `FormDisplay`; a template reads each
field through one handle (`form.email.value` / `form.email.errors`).
"""

from __future__ import annotations

import pytest

from plain.forms import Error, FieldDisplay, Form, FormDisplay, types
from plain.utils.datastructures import MultiValueDict


class ProfileForm(Form):
    name = types.TextField()
    email = types.EmailField()
    bio = types.TextField(required=False)


class TestBlank:
    def test_field_has_empty_value_and_no_errors(self):
        form = FormDisplay(ProfileForm)
        assert form.name.value == ""
        assert form.name.errors == []

    def test_no_form_level_errors(self):
        assert FormDisplay(ProfileForm).errors == []

    def test_values_pre_fill_fields(self):
        form = FormDisplay(ProfileForm, values={"email": "a@b.com"})
        assert form.email.value == "a@b.com"
        assert form.name.value == ""

    def test_blank_form_shows_each_field_initial(self):
        class Defaulted(Form):
            mode = types.TextField(initial="draft")

        assert FormDisplay(Defaulted).mode.value == "draft"

    def test_passed_values_override_field_initial(self):
        class Defaulted(Form):
            mode = types.TextField(initial="draft")

        assert FormDisplay(Defaulted, values={"mode": "live"}).mode.value == "live"


class TestFromInvalid:
    def test_field_carries_submitted_value_and_its_errors(self):
        result = ProfileForm.validate({"name": "Dave", "email": "bad"})
        assert not result
        form = FormDisplay(ProfileForm, result)
        # email was submitted but invalid
        assert form.email.value == "bad"
        assert form.email.errors
        assert form.email.errors[0].field == "email"
        # name was fine
        assert form.name.value == "Dave"
        assert form.name.errors == []

    def test_form_level_errors_kept_off_fields(self):
        class Whole(Form):
            a = types.TextField()

            def check(self):
                return [Error("Whole-form problem.", code="bad")]

        result = Whole.validate({"a": "x"})
        assert not result
        form = FormDisplay(Whole, result)
        assert len(form.errors) == 1
        assert form.errors[0].field is None
        assert form.a.errors == []


class TestHandBuilt:
    def test_errors_and_values_kwargs(self):
        form = FormDisplay(
            ProfileForm,
            errors=[Error("Taken.", code="taken", field="email")],
            values={"email": "a@b.com"},
        )
        assert form.email.value == "a@b.com"
        assert form.email.errors[0].code == "taken"

    def test_none_value_renders_as_empty_string(self):
        # An edit form's initial values carry `None` for an empty optional
        # field — an input shows it as "", never the text "None".
        form = FormDisplay(ProfileForm, values={"name": None})
        assert form.name.value == ""


class TestAccess:
    def test_item_access(self):
        form = FormDisplay(ProfileForm, values={"name": "Dave"})
        assert form["name"].value == "Dave"

    def test_iteration_yields_every_field_in_order(self):
        form = FormDisplay(ProfileForm)
        assert [f.name for f in form] == ["name", "email", "bio"]
        assert all(isinstance(f, FieldDisplay) for f in form)

    def test_unknown_field_attr_raises(self):
        form = FormDisplay(ProfileForm)
        with pytest.raises(AttributeError):
            getattr(form, "not_a_field")

    def test_unknown_field_item_raises(self):
        form = FormDisplay(ProfileForm)
        with pytest.raises(KeyError):
            form["not_a_field"]

    def test_in_operator_checks_field_membership(self):
        form = FormDisplay(ProfileForm)
        assert "email" in form
        assert "not_a_field" not in form

    def test_multi_value_field_keeps_every_submitted_value(self):
        class Picker(Form):
            picks = types.MultipleChoiceField(choices=[("a", "A"), ("b", "B")])

        # A multi-valued source (a re-rendered submission) yields the full list.
        form = FormDisplay(Picker, values=MultiValueDict({"picks": ["a", "b"]}))
        assert form.picks.value == ["a", "b"]


class TestErrorFieldGuard:
    """An Error referencing a non-existent field used to disappear silently —
    it matched neither per-field rendering nor the form-level errors list.
    Construction now rejects it so the typo surfaces at the view→template seam."""

    def test_unknown_field_in_errors_raises(self):
        with pytest.raises(ValueError, match="unknown field"):
            FormDisplay(
                ProfileForm,
                errors=[Error("Bad.", code="invalid", field="emial")],
            )

    def test_form_level_error_still_allowed(self):
        FormDisplay(ProfileForm, errors=[Error("Bad.", code="invalid")])


class TestFieldDisplay:
    def test_attributes(self):
        field = FormDisplay(ProfileForm, values={"name": "Dave"}).name
        assert isinstance(field, FieldDisplay)
        assert field.name == "name"
        assert field.value == "Dave"
        assert field.errors == []

    def test_required_reflects_the_schema_field(self):
        form = FormDisplay(ProfileForm)
        assert form.name.required is True
        assert form.bio.required is False  # bio is declared required=False

    def test_html_id_pairs_input_with_label(self):
        assert FormDisplay(ProfileForm).email.html_id == "id_email"

    def test_choices_empty_for_a_non_choice_field(self):
        assert FormDisplay(ProfileForm).name.choices == []

    def test_choices_carried_from_a_choice_field(self):
        class Picker(Form):
            color = types.ChoiceField(choices=[("r", "Red"), ("g", "Green")])

        assert FormDisplay(Picker).color.choices == [("r", "Red"), ("g", "Green")]
