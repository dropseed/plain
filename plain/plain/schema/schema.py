from __future__ import annotations

from typing import Any, ClassVar, Self, cast

from plain.exceptions import ValidationError
from plain.forms.fields import Field, FileField, MultipleChoiceField

from .result import Invalid

__all__ = ("Schema", "make_schema")


class SchemaMeta(type):
    """Collect Field instances declared on the class into `_schema_fields`.

    Field declarations look like `email: str = EmailField()`. The annotation
    drives type-checker visibility into the cleaned instance attributes; the
    Field instance drives runtime parsing/validation.
    """

    def __new__(
        mcs: type[SchemaMeta],
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
        setattr(new_cls, "_schema_fields", fields)  # noqa: B010
        return new_cls


class Schema(metaclass=SchemaMeta):
    """Pure validating parser.

    Subclass to declare fields:

        class ContactSchema(Schema):
            email: str = EmailField()
            message: str = TextField(max_length=2000)

    Or build inline with `make_schema(...)`:

        ContactSchema = make_schema(email=EmailField(), message=TextField())

    Validate a dict and dispatch on the result type. The schema class
    plays double duty: `Schema.validate()` returns either an instance of
    the schema (success) or `Invalid` (failure). Eliminate `Invalid` to
    narrow:

        result = ContactSchema.validate(data)
        if isinstance(result, Invalid):
            return ...                # handle errors
        # result is the typed schema instance — no `.data` indirection
        contact = result
        contact.email                 # str

    Override `check()` (instance method) for cross-field validation that
    runs after fields have cleaned successfully.
    """

    _schema_fields: ClassVar[dict[str, Field]] = {}

    def __init__(self, **data: Any) -> None:
        for name in self._schema_fields:
            if name in data:
                object.__setattr__(self, name, data[name])
        object.__setattr__(self, "_frozen", True)

    def __setattr__(self, name: str, value: Any) -> None:
        # Schemas are frozen after construction. Mutating a validated
        # instance defeats the contract — `result.email` is supposed to
        # carry the cleaned value, not whatever someone assigned later.
        if getattr(self, "_frozen", False):
            raise AttributeError(
                f"{type(self).__name__} is frozen — schema instances are "
                f"immutable after validation; cannot set {name!r}."
            )
        object.__setattr__(self, name, value)

    def __delattr__(self, name: str) -> None:
        if getattr(self, "_frozen", False):
            raise AttributeError(
                f"{type(self).__name__} is frozen — cannot delete {name!r}."
            )
        object.__delattr__(self, name)

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

    def apply_to[Instance](self, instance: Instance) -> Instance:
        """Copy validated field values onto an existing object — typically
        a model instance about to be saved.

        Walks `_schema_fields`, calling `setattr(instance, name, value)` for
        each field that's set on the schema. Fields missing from the schema
        instance (e.g. after `partial=True` validation) are skipped, leaving
        the target's existing value intact. Returns `instance` for chaining.

            class EditContactView(View):
                def post(self):
                    result = ContactSchema.validate(self.request.form_data)
                    if isinstance(result, Invalid):
                        return self.render(form=BoundSchema.from_invalid(...))
                    result.apply_to(self.contact).save()
                    return RedirectResponse(...)

        Field-name mismatches (schema field doesn't exist on the target)
        raise `AttributeError` only if the target uses ``__slots__`` —
        regular Python objects accept arbitrary attribute assignment, so
        the caller is responsible for keeping schema and target field
        names aligned.
        """
        for name in self._schema_fields:
            if hasattr(self, name):
                setattr(instance, name, getattr(self, name))
        return instance

    def check(
        self, *, context: dict[str, Any] | None = None
    ) -> dict[str, list[str]] | None:
        """Cross-field validation hook. Override in subclasses.

        Runs after every field has cleaned successfully; `self` is the
        typed instance with all cleaned values set, so subclass overrides
        get full type-checker support without a Liskov violation. Return a
        dict of field-name → error messages (use `"__all__"` for non-field
        errors) or `None` when there are no errors. Raising
        `ValidationError` is also supported.
        """
        return None

    @classmethod
    def validate(
        cls,
        data: dict[str, Any] | None,
        *,
        files: Any = None,
        context: dict[str, Any] | None = None,
        partial: bool = False,
    ) -> Self | Invalid:
        """Validate `data` against this schema.

        Returns either an instance of `cls` (cleaned, typed values set as
        attributes) or `Invalid` (per-field errors). Never raises on
        validation failure.

        For file uploads, pass `request.files` (a `MultiValueDict[str,
        UploadedFile]`) as `files=`. `FileField`/`ImageField` declarations
        are populated from `files` instead of `data`; everything else
        reads from `data` as usual.

        Set `partial=True` to validate only the fields present in `data`/
        `files` — missing required fields don't error and `check()` is
        skipped. Useful for HTMX live-validation where each keystroke
        sends just one field.
        """
        raw = data or {}
        files_map: dict[str, Any] = files if files is not None else {}
        cleaned: dict[str, Any] = {}
        errors: dict[str, list[str]] = {}
        # MultiValueDict carries multi-valued keys; plain dicts don't. For
        # multi-select fields we need to pull all values, not just the last.
        is_multi_value_dict = hasattr(raw, "getlist")

        for name, field in cls._schema_fields.items():
            is_file_field = isinstance(field, FileField)
            present = name in (files_map if is_file_field else raw)
            if partial and not present:
                continue

            if is_file_field:
                raw_value = files_map.get(name)
                try:
                    # FileField.clean takes (data, initial=None)
                    cleaned[name] = field.clean(raw_value, None)
                except ValidationError as e:
                    errors[name] = list(e.messages)
            else:
                if is_multi_value_dict and isinstance(field, MultipleChoiceField):
                    raw_value = raw.getlist(name)  # ty: ignore[unresolved-attribute]
                else:
                    raw_value = raw.get(name)
                try:
                    cleaned[name] = field.clean(raw_value)
                except ValidationError as e:
                    errors[name] = list(e.messages)

        if errors:
            return Invalid(errors=errors, raw=raw)

        instance = cls(**cleaned)

        if partial:
            return instance

        # Cross-field hook — runs only on full validation.
        extra_errors: dict[str, list[str]] | None
        try:
            extra_errors = instance.check(context=context)
        except ValidationError as e:
            if hasattr(e, "error_dict"):
                # Each error_list is a list of ValidationError objects; wrap
                # in a ValidationError to flatten back to message strings.
                extra_errors = {
                    field: [str(m) for m in ValidationError(error_list)]
                    for field, error_list in e.error_dict.items()
                }
            else:
                extra_errors = {"__all__": list(e.messages)}

        if extra_errors:
            return Invalid(errors=dict(extra_errors), raw=raw)

        return instance


def make_schema(name: str = "InlineSchema", /, **fields: Field) -> type[Schema]:
    """Construct an anonymous `Schema` subclass from keyword field definitions.

    Useful for one-off validation in a view body where declaring a named class
    would be ceremony. Returns an untyped result; for typed access, declare a
    real subclass.
    """
    namespace: dict[str, Any] = {"__annotations__": {}, **fields}
    return cast(type[Schema], SchemaMeta(name, (Schema,), namespace))
