from __future__ import annotations

from types import SimpleNamespace

import pytest

from plain.exceptions import ValidationError
from plain.internal.files.uploadedfile import SimpleUploadedFile, UploadedFile
from plain.schema import Field, Invalid, Schema, types


class ContactSchema(Schema):
    email = types.EmailField()
    age = types.IntegerField(min_value=0, max_value=150)
    message = types.TextField(max_length=2000)


def test_valid_returns_typed_instance():
    result = ContactSchema.validate(
        {"email": "a@b.co", "age": "42", "message": "hello"}
    )
    assert not isinstance(result, Invalid)
    assert isinstance(result, ContactSchema)
    assert result.email == "a@b.co"
    assert result.age == 42  # coerced from string
    assert result.message == "hello"


def test_invalid_returns_per_field_errors():
    result = ContactSchema.validate(
        {"email": "not-an-email", "age": "-1", "message": ""}
    )
    assert isinstance(result, Invalid)
    assert "email" in result.errors
    assert "age" in result.errors
    assert "message" in result.errors
    # Errors are lists of strings, JSON-ready
    assert all(
        isinstance(msgs, list) and all(isinstance(m, str) for m in msgs)
        for msgs in result.errors.values()
    )
    # raw input preserved for re-rendering
    assert result.raw == {"email": "not-an-email", "age": "-1", "message": ""}


def test_missing_required_field_is_invalid():
    result = ContactSchema.validate({})
    assert isinstance(result, Invalid)
    assert set(result.errors) == {"email", "age", "message"}


def test_validate_handles_none_input():
    result = ContactSchema.validate(None)
    assert isinstance(result, Invalid)


def test_fields_classmethod_exposes_declared_fields():
    """`fields()` is the public introspection surface — name -> Field."""
    fields = ContactSchema.fields()
    assert list(fields) == ["email", "age", "message"]
    assert all(isinstance(f, Field) for f in fields.values())
    # A copy — mutating it doesn't disturb the schema.
    fields.clear()
    assert list(ContactSchema.fields()) == ["email", "age", "message"]


def test_schema_inheritance_carries_fields():
    class Extended(ContactSchema):
        priority = types.ChoiceField(choices=[("low", "Low"), ("high", "High")])

    result = Extended.validate(
        {"email": "a@b.co", "age": "1", "message": "hi", "priority": "low"}
    )
    assert not isinstance(result, Invalid)
    assert result.email == "a@b.co"
    assert result.priority == "low"


def test_schema_repr_shows_field_values():
    result = ContactSchema.validate({"email": "a@b.co", "age": "1", "message": "hi"})
    assert not isinstance(result, Invalid)
    rep = repr(result)
    assert "ContactSchema(" in rep
    assert "email='a@b.co'" in rep


def test_schema_equality_by_field_values():
    a = ContactSchema.validate({"email": "a@b.co", "age": "1", "message": "x"})
    b = ContactSchema.validate({"email": "a@b.co", "age": "1", "message": "x"})
    c = ContactSchema.validate({"email": "a@b.co", "age": "2", "message": "x"})
    assert not isinstance(a, Invalid)
    assert not isinstance(b, Invalid)
    assert not isinstance(c, Invalid)
    assert a == b
    assert a != c


def test_no_form_request_required():
    """Schemas validate plain dicts — no request, no HTTP, no fakes."""
    result = ContactSchema.validate({"email": "a@b.co", "age": "1", "message": "x"})
    assert not isinstance(result, Invalid)


# ---------------------------------------------------------------------------
# check() — cross-field validation hook (instance method)
# ---------------------------------------------------------------------------


def test_check_returning_dict_adds_errors():
    class S(Schema):
        a = types.IntegerField()
        b = types.IntegerField()

        def check(self, *, context=None):
            if self.a > self.b:
                return {"__all__": ["a must be <= b"]}
            return None

    assert not isinstance(S.validate({"a": "1", "b": "2"}), Invalid)

    bad = S.validate({"a": "5", "b": "2"})
    assert isinstance(bad, Invalid)
    assert bad.errors == {"__all__": ["a must be <= b"]}


def test_check_raising_validationerror_string_attaches_to_all():
    class S(Schema):
        a = types.IntegerField()

        def check(self, *, context=None):
            raise ValidationError("global problem")

    bad = S.validate({"a": "1"})
    assert isinstance(bad, Invalid)
    assert bad.errors == {"__all__": ["global problem"]}


def test_check_raising_validationerror_dict_attaches_per_field():
    class S(Schema):
        a = types.IntegerField()
        b = types.IntegerField()

        def check(self, *, context=None):
            raise ValidationError({"a": ["too big"], "b": "too small"})

    bad = S.validate({"a": "1", "b": "2"})
    assert isinstance(bad, Invalid)
    assert bad.errors == {"a": ["too big"], "b": ["too small"]}


def test_check_does_not_run_when_field_errors_exist():
    """If any field fails, check() must not see a half-populated instance."""
    seen: list[bool] = []

    class S(Schema):
        a = types.IntegerField()
        b = types.IntegerField()

        def check(self, *, context=None):
            seen.append(True)
            return None

    bad = S.validate({"a": "not-a-number", "b": "1"})
    assert isinstance(bad, Invalid)
    assert seen == []  # check() never called


def test_check_self_is_typed_instance():
    captured: list = []

    class S(Schema):
        a = types.IntegerField()
        name = types.TextField()

        def check(self, *, context=None):
            # `self` is a typed S instance — attribute access works.
            captured.append((self.a, self.name))
            return None

    S.validate({"a": "42", "name": "ok"})
    assert captured == [(42, "ok")]


def test_check_receives_context():
    captured: list = []

    class S(Schema):
        a = types.IntegerField()

        def check(self, *, context=None):
            captured.append(context)
            return None

    S.validate({"a": "1"}, context={"user_id": 42})
    assert captured == [{"user_id": 42}]


def test_default_check_is_noop():
    """Schemas without an override pass through cleanly."""

    class S(Schema):
        a = types.IntegerField()

    result = S.validate({"a": "1"})
    assert not isinstance(result, Invalid)
    assert result.a == 1


# ---------------------------------------------------------------------------
# validate_partial() — HTMX live-validation
# ---------------------------------------------------------------------------


def test_partial_skips_missing_required_fields():
    class S(Schema):
        title = types.TextField(min_length=1)
        priority = types.ChoiceField(choices=[("low", "Low"), ("high", "High")])

    # `priority` is missing but skipped; the present field passes — no errors.
    assert S.validate_partial({"title": "ok"}) is None


def test_partial_still_reports_errors_on_present_fields():
    class S(Schema):
        title = types.TextField(min_length=5)
        priority = types.ChoiceField(choices=[("low", "Low")])

    result = S.validate_partial({"title": "x"})
    assert isinstance(result, Invalid)
    assert "title" in result.errors
    assert "priority" not in result.errors


def test_partial_skips_check_hook():
    seen: list[bool] = []

    class S(Schema):
        a = types.IntegerField()
        b = types.IntegerField()

        def check(self, *, context=None):
            seen.append(True)
            return None

    S.validate_partial({"a": "1"})
    assert seen == []  # check() never called

    S.validate({"a": "1", "b": "2"})
    assert seen == [True]


def test_partial_empty_input_is_valid():
    class S(Schema):
        title = types.TextField()

    assert S.validate_partial({}) is None


# ---------------------------------------------------------------------------
# files= kwarg — file upload support
# ---------------------------------------------------------------------------


def _file(name: str = "report.pdf", content: bytes = b"hello") -> UploadedFile:
    return SimpleUploadedFile(name, content, "application/pdf")


def test_filefield_reads_from_files_not_data():
    class Upload(Schema):
        title = types.TextField()
        document = types.FileField()

    f = _file()
    result = Upload.validate({"title": "Q3"}, files={"document": f})
    assert not isinstance(result, Invalid)
    assert result.title == "Q3"
    assert result.document.name == "report.pdf"
    assert result.document.size == len(b"hello")


def test_filefield_missing_is_required_error():
    class Upload(Schema):
        document = types.FileField()

    result = Upload.validate({}, files={})
    assert isinstance(result, Invalid)
    assert "document" in result.errors


def test_filefield_optional_when_required_false():
    class Upload(Schema):
        title = types.TextField()
        avatar = types.FileField(required=False)

    result = Upload.validate({"title": "x"})
    assert not isinstance(result, Invalid)
    assert result.title == "x"


def test_partial_includes_files_for_presence_check():
    class Upload(Schema):
        title = types.TextField(min_length=1)
        document = types.FileField()

    # `title` is missing but skipped; the file IS present, so it gets
    # validated — an empty upload fails, proving files join the presence check.
    empty = _file("empty.pdf", b"")
    result = Upload.validate_partial({}, files={"document": empty})
    assert isinstance(result, Invalid)
    assert "document" in result.errors
    assert "title" not in result.errors


def test_files_default_to_empty_dict():
    """Schemas without FileField don't need files= to be passed."""

    class S(Schema):
        title = types.TextField()

    result = S.validate({"title": "x"})
    assert not isinstance(result, Invalid)


def test_filefield_with_other_field_errors():
    """File fields and regular fields error independently."""

    class Upload(Schema):
        title = types.TextField(min_length=5)
        document = types.FileField()

    result = Upload.validate({"title": "x"}, files={})
    assert isinstance(result, Invalid)
    assert "title" in result.errors
    assert "document" in result.errors


# ---------------------------------------------------------------------------
# apply_to(instance) — schema-to-model helper
# ---------------------------------------------------------------------------


def test_apply_to_copies_validated_fields_onto_instance():
    class S(Schema):
        title = types.TextField(min_length=1)
        priority = types.ChoiceField(choices=[("low", "L"), ("high", "H")])

    result = S.validate({"title": "Q3", "priority": "high"})
    assert not isinstance(result, Invalid)

    target = SimpleNamespace(title="old", priority="low", unrelated="kept")
    returned = result.apply_to(target)

    assert returned is target  # chainable
    assert target.title == "Q3"
    assert target.priority == "high"
    assert target.unrelated == "kept"  # untouched fields not clobbered


def test_schema_instance_is_frozen():
    """Schemas are immutable after validation — accidentally re-assigning
    a field on the result would silently lie about what was validated."""

    class S(Schema):
        a = types.IntegerField()

    result = S.validate({"a": "1"})
    assert not isinstance(result, Invalid)
    assert result.a == 1

    with pytest.raises(AttributeError, match="frozen"):
        result.a = 99  # ty: ignore[invalid-assignment]  (deliberate frozen violation)

    with pytest.raises(AttributeError, match="frozen"):
        result.unrelated = "x"

    with pytest.raises(AttributeError, match="frozen"):
        del result.a


def test_apply_to_skips_unset_fields():
    """A schema built without every field (constructed directly, not via
    validate()) must not zero out the target's unset fields."""

    class S(Schema):
        title = types.TextField()
        priority = types.ChoiceField(choices=[("low", "L"), ("high", "H")])

    # An instance with only `title` set — `priority` stays unset.
    result = S(title="Q3")
    assert not hasattr(result, "priority")

    target = SimpleNamespace(title="old", priority="low")
    result.apply_to(target)

    assert target.title == "Q3"
    assert target.priority == "low"  # preserved
