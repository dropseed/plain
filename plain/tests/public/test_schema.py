from __future__ import annotations

from plain.schema import Invalid, Schema, Valid, make_schema, types


class ContactSchema(Schema):
    email: str = types.EmailField()
    age: int = types.IntegerField(min_value=0, max_value=150)
    message: str = types.TextField(max_length=2000)


def test_valid_returns_typed_instance():
    result = ContactSchema.validate(
        {"email": "a@b.co", "age": "42", "message": "hello"}
    )
    assert isinstance(result, Valid)
    assert isinstance(result.data, ContactSchema)
    assert result.data.email == "a@b.co"
    assert result.data.age == 42  # coerced from string
    assert result.data.message == "hello"
    assert result.raw == {"email": "a@b.co", "age": "42", "message": "hello"}


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
    assert isinstance(result, Valid)
    assert result.data.host == "example.com"
    assert result.data.port == 8080


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
    assert isinstance(result, Valid)
    assert result.data.email == "a@b.co"
    assert result.data.priority == "low"


def test_schema_repr_shows_field_values():
    result = ContactSchema.validate({"email": "a@b.co", "age": "1", "message": "hi"})
    assert isinstance(result, Valid)
    rep = repr(result.data)
    assert "ContactSchema(" in rep
    assert "email='a@b.co'" in rep


def test_schema_equality_by_field_values():
    a = ContactSchema.validate({"email": "a@b.co", "age": "1", "message": "x"})
    b = ContactSchema.validate({"email": "a@b.co", "age": "1", "message": "x"})
    c = ContactSchema.validate({"email": "a@b.co", "age": "2", "message": "x"})
    assert isinstance(a, Valid)
    assert isinstance(b, Valid)
    assert isinstance(c, Valid)
    assert a.data == b.data
    assert a.data != c.data


def test_no_form_request_required():
    """Schemas validate plain dicts — no request, no HTTP, no fakes."""
    result = ContactSchema.validate({"email": "a@b.co", "age": "1", "message": "x"})
    assert isinstance(result, Valid)
