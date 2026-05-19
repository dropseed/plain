"""Public contract — `plain.forms` validation.

`Form.validate()` is the contract: untrusted input in, a typed `Form` or an
`Invalid` out. A failure here is a user-visible behavior change.
"""

from __future__ import annotations

import pytest

from plain.exceptions import ValidationError
from plain.forms import Error, Form, types


class ContactForm(Form):
    email = types.EmailField()
    age = types.IntegerField(required=False)


class TestValidateSuccess:
    def test_returns_form_instance(self):
        result = ContactForm.validate({"email": "a@b.com", "age": "7"})
        assert isinstance(result, ContactForm)

    def test_success_is_truthy(self):
        assert ContactForm.validate({"email": "a@b.com"})

    def test_cleaned_values_are_typed(self):
        result = ContactForm.validate({"email": "a@b.com", "age": "7"})
        assert result
        assert result.email == "a@b.com"
        assert result.age == 7  # "7" cleaned to int

    def test_optional_field_absent_cleans_to_none(self):
        result = ContactForm.validate({"email": "a@b.com"})
        assert result
        assert result.age is None

    def test_unknown_keys_are_ignored(self):
        result = ContactForm.validate({"email": "a@b.com", "bogus": "x"})
        assert result
        assert not hasattr(result, "bogus")


class TestValidateFailure:
    def test_returns_falsy_invalid(self):
        result = ContactForm.validate({"email": "not-an-email"})
        assert not result
        assert bool(result) is False

    def test_validate_accepts_none_data(self):
        result = ContactForm.validate(None)
        assert not result

    def test_errors_is_a_flat_list_of_errors(self):
        result = ContactForm.validate({"email": "bad", "age": "bad"})
        assert not result
        assert isinstance(result.errors, list)
        assert all(isinstance(e, Error) for e in result.errors)

    def test_every_failing_field_is_reported(self):
        result = ContactForm.validate({"email": "bad", "age": "notnum"})
        assert not result
        assert {e.field for e in result.errors} == {"email", "age"}

    def test_required_field_missing(self):
        result = ContactForm.validate({})
        assert not result
        on_email = [e for e in result.errors if e.field == "email"]
        assert len(on_email) == 1
        assert on_email[0].code == "required"

    def test_raw_preserves_submitted_input(self):
        data = {"email": "bad", "age": "12"}
        result = ContactForm.validate(data)
        assert not result
        assert result.raw == data


class TestError:
    def test_carries_message_code_and_field(self):
        e = Error("Bad.", code="invalid", field="email")
        assert (e.message, e.code, e.field) == ("Bad.", "invalid", "email")

    def test_field_defaults_to_none_for_form_level(self):
        assert Error("Whole form.", code="bad").field is None


class TestCheck:
    def test_runs_after_fields_clean_and_can_reject(self):
        class Signup(Form):
            password = types.TextField()
            confirm = types.TextField()

            def check(self):
                if self.password != self.confirm:
                    return [Error("Mismatch.", code="mismatch", field="confirm")]
                return None

        assert Signup.validate({"password": "x", "confirm": "x"})

        bad = Signup.validate({"password": "x", "confirm": "y"})
        assert not bad
        assert bad.errors == [Error("Mismatch.", code="mismatch", field="confirm")]

    def test_error_with_no_field_is_form_level(self):
        class F(Form):
            x = types.TextField()

            def check(self):
                return [Error("Whole-form problem.", code="bad")]

        result = F.validate({"x": "y"})
        assert not result
        assert result.errors[0].field is None

    def test_does_not_run_when_a_field_fails(self):
        # check() reads self.<field> — it must only run once every field
        # has cleaned, so a field failure short-circuits before it.
        ran: list[bool] = []

        class F(Form):
            x = types.IntegerField()

            def check(self):
                ran.append(True)
                return None

        F.validate({"x": "not-a-number"})
        assert ran == []

    def test_raised_validation_error_is_folded_in(self):
        class F(Form):
            x = types.TextField()

            def check(self):
                raise ValidationError("Raised.", code="raised")

        result = F.validate({"x": "y"})
        assert not result
        assert result.errors[0].code == "raised"


class TestReservedFieldNames:
    """`_frozen` is used internally as the immutability sentinel — a user
    field with that name would silently lose its cleaned value."""

    def test_reserved_name_raises_at_declaration(self):
        with pytest.raises(TypeError, match="reserved by Form internals"):

            class Bad(Form):
                _frozen = types.TextField()


class TestFormIntrospection:
    def test_fields_lists_declared_fields_in_order(self):
        assert list(ContactForm.fields()) == ["email", "age"]

    def test_subclass_inherits_parent_fields(self):
        class Base(Form):
            a = types.TextField()

        class Child(Base):
            b = types.TextField()

        assert list(Child.fields()) == ["a", "b"]

    def test_validated_instance_is_frozen(self):
        result = ContactForm.validate({"email": "a@b.com"})
        assert result
        with pytest.raises(AttributeError):
            result.email = "changed@b.com"  # ty: ignore[invalid-assignment]


class TestEqualityAndHashing:
    """A `Form` instance carries the cleaned values, so two results from the
    same input compare equal and hash the same — usable as a dict key or in a
    set. A different form class with the same fields never compares equal."""

    def test_same_input_compares_equal(self):
        a = ContactForm.validate({"email": "a@b.com", "age": "7"})
        b = ContactForm.validate({"email": "a@b.com", "age": "7"})
        assert a == b
        assert hash(a) == hash(b)

    def test_different_input_compares_unequal(self):
        a = ContactForm.validate({"email": "a@b.com"})
        b = ContactForm.validate({"email": "c@d.com"})
        assert a != b

    def test_different_form_classes_never_compare_equal(self):
        class OtherForm(Form):
            email = types.EmailField()
            age = types.IntegerField(required=False)

        assert ContactForm.validate({"email": "a@b.com"}) != OtherForm.validate(
            {"email": "a@b.com"}
        )

    def test_multi_value_field_stays_hashable(self):
        # MultipleChoiceField cleans to a list — make_hashable converts it to
        # a tuple so the result still hashes.
        class Picker(Form):
            picks = types.MultipleChoiceField(choices=[("a", "A"), ("b", "B")])

        result = Picker.validate({"picks": ["a", "b"]})
        assert result
        assert hash(result) == hash(Picker.validate({"picks": ["a", "b"]}))
