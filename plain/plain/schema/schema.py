from __future__ import annotations

from typing import Any, ClassVar, Self

from plain.exceptions import ValidationError
from plain.forms.fields import Field

from .result import Invalid, Valid

__all__ = ("Schema", "make_schema")


class SchemaMeta(type):
    """Collect Field instances declared on the class into `_schema_fields`.

    Field declarations look like `email: str = EmailField()`. The annotation
    drives type-checker visibility into the cleaned instance attributes; the
    Field instance drives runtime parsing/validation.
    """

    def __new__(
        mcs,
        name: str,
        bases: tuple[type, ...],
        namespace: dict[str, Any],
    ) -> type:
        fields: dict[str, Field] = {}

        # Inherit fields from base classes (in MRO order).
        for base in bases:
            base_fields = getattr(base, "_schema_fields", None)
            if base_fields:
                fields.update(base_fields)

        # Pop Field instances from the class body and register them.
        # We pop them so __init__ can set the cleaned value as an attribute.
        for key in list(namespace):
            value = namespace[key]
            if isinstance(value, Field):
                fields[key] = value
                del namespace[key]

        new_cls = super().__new__(mcs, name, bases, namespace)
        new_cls._schema_fields = fields
        return new_cls


class Schema(metaclass=SchemaMeta):
    """Pure validating parser.

    Subclass to declare fields:

        class ContactSchema(Schema):
            email: str = EmailField()
            message: str = TextField(max_length=2000)

    Or build inline with `make_schema(...)`:

        ContactSchema = make_schema(email=EmailField(), message=TextField())

    Validate a dict and dispatch on the result type:

        match ContactSchema.validate(data):
            case Valid(data=contact):
                ...   # contact: ContactSchema, fully typed
            case Invalid(errors=errs):
                ...
    """

    _schema_fields: ClassVar[dict[str, Field]] = {}

    def __init__(self, **data: Any) -> None:
        for name in self._schema_fields:
            if name in data:
                setattr(self, name, data[name])

    def __repr__(self) -> str:
        attrs = ", ".join(
            f"{k}={getattr(self, k, '<unset>')!r}" for k in self._schema_fields
        )
        return f"{type(self).__name__}({attrs})"

    def __eq__(self, other: object) -> bool:
        if type(self) is not type(other):
            return NotImplemented
        return all(
            getattr(self, k, None) == getattr(other, k, None)
            for k in self._schema_fields
        )

    def __hash__(self) -> int:
        return hash(tuple(getattr(self, k, None) for k in self._schema_fields))

    @classmethod
    def validate(
        cls,
        data: dict[str, Any] | None,
        *,
        context: dict[str, Any] | None = None,
    ) -> Valid[Self] | Invalid:
        """Validate `data` against this schema.

        Returns either `Valid[Self]` (cleaned typed instance) or `Invalid`
        (per-field errors). Never raises on validation failure.
        """
        raw = data or {}
        cleaned: dict[str, Any] = {}
        errors: dict[str, list[str]] = {}

        for name, field in cls._schema_fields.items():
            raw_value = raw.get(name)
            try:
                cleaned[name] = field.clean(raw_value)
            except ValidationError as e:
                errors[name] = list(e.messages)

        if errors:
            return Invalid(errors=errors, raw=raw)

        return Valid(data=cls(**cleaned), raw=raw)


def make_schema(name: str = "InlineSchema", /, **fields: Field) -> type[Schema]:
    """Construct an anonymous `Schema` subclass from keyword field definitions.

    Useful for one-off validation in a view body where declaring a named class
    would be ceremony. Returns an untyped result; for typed access, declare a
    real subclass.
    """
    namespace: dict[str, Any] = {"__annotations__": {}, **fields}
    return SchemaMeta(name, (Schema,), namespace)
