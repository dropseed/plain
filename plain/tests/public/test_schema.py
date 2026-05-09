from __future__ import annotations

from plain.schema import Invalid, Schema, make_schema, types


class ContactSchema(Schema):
    email: str = types.EmailField()
    age: int = types.IntegerField(min_value=0, max_value=150)
    message: str = types.TextField(max_length=2000)


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


def test_inline_schema_via_make_schema():
    PingSchema = make_schema(
        host=types.TextField(min_length=1),
        port=types.IntegerField(min_value=1, max_value=65535),
    )
    result = PingSchema.validate({"host": "example.com", "port": "8080"})
    assert not isinstance(result, Invalid)
    assert result.host == "example.com"
    assert result.port == 8080


def test_inline_schema_invalid():
    PingSchema = make_schema(host=types.TextField(min_length=1))
    result = PingSchema.validate({"host": ""})
    assert isinstance(result, Invalid)
    assert "host" in result.errors


def test_schema_inheritance_carries_fields():
    class Extended(ContactSchema):
        priority: str = types.ChoiceField(choices=[("low", "Low"), ("high", "High")])

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
        a: int = types.IntegerField()
        b: int = types.IntegerField()

        def check(self, *, context=None):
            if self.a > self.b:
                return {"__all__": ["a must be <= b"]}
            return None

    assert not isinstance(S.validate({"a": "1", "b": "2"}), Invalid)

    bad = S.validate({"a": "5", "b": "2"})
    assert isinstance(bad, Invalid)
    assert bad.errors == {"__all__": ["a must be <= b"]}


def test_check_raising_validationerror_string_attaches_to_all():
    from plain.exceptions import ValidationError

    class S(Schema):
        a: int = types.IntegerField()

        def check(self, *, context=None):
            raise ValidationError("global problem")

    bad = S.validate({"a": "1"})
    assert isinstance(bad, Invalid)
    assert bad.errors == {"__all__": ["global problem"]}


def test_check_raising_validationerror_dict_attaches_per_field():
    from plain.exceptions import ValidationError

    class S(Schema):
        a: int = types.IntegerField()
        b: int = types.IntegerField()

        def check(self, *, context=None):
            raise ValidationError({"a": ["too big"], "b": "too small"})

    bad = S.validate({"a": "1", "b": "2"})
    assert isinstance(bad, Invalid)
    assert bad.errors == {"a": ["too big"], "b": ["too small"]}


def test_check_does_not_run_when_field_errors_exist():
    """If any field fails, check() must not see a half-populated instance."""
    seen: list[bool] = []

    class S(Schema):
        a: int = types.IntegerField()
        b: int = types.IntegerField()

        def check(self, *, context=None):
            seen.append(True)
            return None

    bad = S.validate({"a": "not-a-number", "b": "1"})
    assert isinstance(bad, Invalid)
    assert seen == []  # check() never called


def test_check_self_is_typed_instance():
    captured: list = []

    class S(Schema):
        a: int = types.IntegerField()
        name: str = types.TextField()

        def check(self, *, context=None):
            # `self` is a typed S instance — attribute access works.
            captured.append((self.a, self.name))
            return None

    S.validate({"a": "42", "name": "ok"})
    assert captured == [(42, "ok")]


def test_check_receives_context():
    captured: list = []

    class S(Schema):
        a: int = types.IntegerField()

        def check(self, *, context=None):
            captured.append(context)
            return None

    S.validate({"a": "1"}, context={"user_id": 42})
    assert captured == [{"user_id": 42}]


def test_default_check_is_noop():
    """Schemas without an override pass through cleanly."""

    class S(Schema):
        a: int = types.IntegerField()

    result = S.validate({"a": "1"})
    assert not isinstance(result, Invalid)
    assert result.a == 1


# ---------------------------------------------------------------------------
# partial=True — HTMX live-validation
# ---------------------------------------------------------------------------


def test_partial_skips_missing_required_fields():
    class S(Schema):
        title: str = types.TextField(min_length=1)
        priority: str = types.ChoiceField(
            choices=[("low", "Low"), ("high", "High")]
        )

    result = S.validate({"title": "ok"}, partial=True)
    assert not isinstance(result, Invalid)
    assert result.title == "ok"


def test_partial_still_reports_errors_on_present_fields():
    class S(Schema):
        title: str = types.TextField(min_length=5)
        priority: str = types.ChoiceField(choices=[("low", "Low")])

    result = S.validate({"title": "x"}, partial=True)
    assert isinstance(result, Invalid)
    assert "title" in result.errors
    assert "priority" not in result.errors


def test_partial_skips_check_hook():
    seen: list[bool] = []

    class S(Schema):
        a: int = types.IntegerField()
        b: int = types.IntegerField()

        def check(self, *, context=None):
            seen.append(True)
            return None

    S.validate({"a": "1"}, partial=True)
    assert seen == []  # check() never called

    S.validate({"a": "1", "b": "2"})
    assert seen == [True]


def test_partial_empty_input_is_valid():
    class S(Schema):
        title: str = types.TextField()

    result = S.validate({}, partial=True)
    assert not isinstance(result, Invalid)
