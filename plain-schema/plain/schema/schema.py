from __future__ import annotations

from typing import Any, ClassVar, Self

from plain.exceptions import NON_FIELD_ERRORS, ValidationError
from plain.utils.hashable import make_hashable

from .fields import Field, FileField
from .result import Invalid

__all__ = ("Schema",)

# Marks a field with no value on an instance — distinct from a field that
# legitimately cleaned to None. A `validate()` instance always has every
# field set, but one built directly (`Schema(**partial_data)`) can leave
# fields unset. __repr__/__eq__/__hash__ use this so an unset field never
# compares or hashes equal to a real None.
_UNSET = object()


class Schema:
    """Pure validating parser.

    Subclass and declare each field as `name = types.*(...)`:

        from plain.schema import Schema, types

        class ContactSchema(Schema):
            email = types.EmailField()
            message = types.TextField(max_length=2000)

    Each field is a descriptor: `ContactSchema.email` is the typed
    `Field[str]` reference, `result.email` the cleaned `str` value. The
    `types.*` constructors are typed, so both faces are statically
    checked with no annotation to write.

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

    # Populated by __init_subclass__; the empty default is for type-checker
    # visibility and covers `Schema` itself, which declares no fields.
    _schema_fields: ClassVar[dict[str, Field[Any]]] = {}

    def __init_subclass__(cls, **kwargs: Any) -> None:
        """Collect the `Field` instances declared on the class into `_schema_fields`.

        Field declarations look like `email = EmailField()`. Each field
        is a descriptor that stays on the class — `Schema.email` is the
        typed reference, `instance.email` the cleaned value — so this just
        gathers them into one ordered map for validation to walk, merging in
        any fields inherited from base classes.
        """
        super().__init_subclass__(**kwargs)
        fields: dict[str, Field[Any]] = {}
        for base in cls.__bases__:
            base_fields = getattr(base, "_schema_fields", None)
            if base_fields:
                fields.update(base_fields)
        for key, value in vars(cls).items():
            if isinstance(value, Field):
                fields[key] = value
        cls._schema_fields = fields

    @classmethod
    def fields(cls) -> dict[str, Field[Any]]:
        """The declared fields as an ordered ``name -> Field`` map.

        The public introspection surface — walk this to render a schema,
        document it, or drive tooling, without needing a validated
        instance. Returns a copy; the live mapping is internal.
        """
        return dict(cls._schema_fields)

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
        parts = []
        for k in self._schema_fields:
            value = getattr(self, k, _UNSET)
            parts.append(f"{k}=<unset>" if value is _UNSET else f"{k}={value!r}")
        return f"{type(self).__name__}({', '.join(parts)})"

    def __eq__(self, other: object) -> bool:
        if type(self) is not type(other):
            return NotImplemented
        return all(
            getattr(self, k, _UNSET) == getattr(other, k, _UNSET)
            for k in self._schema_fields
        )

    def __hash__(self) -> int:
        # make_hashable converts list-valued fields (e.g. MultipleChoiceField)
        # into tuples so schema instances stay hashable. _UNSET marks a field
        # with no value — it hashes distinctly from a real None.
        values = tuple(getattr(self, k, _UNSET) for k in self._schema_fields)
        return hash(make_hashable(values))

    def apply_to[Instance](self, instance: Instance) -> Instance:
        """Copy validated field values onto an existing object, returning it.

        Walks `_schema_fields`, calling `setattr(instance, name, value)` for
        each field that's set on the schema. A `validate()` result always
        has every field set; a schema built directly from incomplete data
        may not — any unset field is skipped, leaving the target's existing
        value intact.

        This is a pure data move — it never persists. A schema hands its
        cleaned values to a target; whether and how that target is saved is
        the caller's decision:

            result = ContactSchema.validate(self.request.form_data)
            if isinstance(result, Invalid):
                return self.render(form=BoundSchema.from_invalid(...))
            result.apply_to(ContactSubmission()).save()

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
        get full type-checker support without a Liskov violation.

        The contract is return-based, matching `validate()`: return a dict
        of field-name → error messages (use `"__all__"` for non-field
        errors), or `None` when there are no errors. Don't raise — a schema
        is a non-raising parser, and its cross-field hook follows suit.

        (A `ValidationError` raised here is still caught and folded into the
        result rather than escaping, but returning is the documented way.)
        """
        return None

    @classmethod
    def _clean_fields(
        cls,
        raw: Any,
        files_map: dict[str, Any],
        *,
        only_present: bool,
    ) -> tuple[dict[str, Any], dict[str, list[str]]]:
        """Run each declared field's `clean` against `raw`/`files_map`.

        Returns `(cleaned, errors)`. With `only_present=True`, fields absent
        from the input are skipped entirely (partial validation); otherwise
        a missing field is cleaned with `None`, surfacing its required-error.
        """
        cleaned: dict[str, Any] = {}
        errors: dict[str, list[str]] = {}
        # MultiValueDict carries multi-valued keys; plain dicts don't. For
        # multi-select fields we need to pull all values, not just the last.
        is_multi_value_dict = hasattr(raw, "getlist")

        for name, field in cls._schema_fields.items():
            is_file_field = isinstance(field, FileField)
            present = name in (files_map if is_file_field else raw)
            if only_present and not present:
                continue

            try:
                if is_file_field:
                    # FileField.clean takes (data, initial).
                    cleaned[name] = field.clean(files_map.get(name), None)
                elif is_multi_value_dict and field.multi_value:
                    # `raw` has .getlist (verified by the is_multi_value_dict guard).
                    cleaned[name] = field.clean(raw.getlist(name))
                else:
                    cleaned[name] = field.clean(raw.get(name))
            except ValidationError as e:
                errors[name] = list(e.messages)

        return cleaned, errors

    @classmethod
    def validate(
        cls,
        data: dict[str, Any] | None,
        *,
        files: Any = None,
        context: dict[str, Any] | None = None,
    ) -> Self | Invalid:
        """Validate `data` against this schema.

        Returns either an instance of `cls` (cleaned, typed values set as
        attributes) or `Invalid` (per-field errors). Never raises on
        validation failure. A returned instance means *every* declared
        field validated and `check()` passed — `result.<field>` is always
        safe, there is no half-populated instance.

        For file uploads, pass `request.files` (a `MultiValueDict[str,
        UploadedFile]`) as `files=`. `FileField`/`ImageField` declarations
        are populated from `files` instead of `data`; everything else
        reads from `data` as usual.

        For per-field checks against an incomplete payload (HTMX live
        validation), use `validate_partial()` instead.
        """
        raw = data or {}
        files_map: dict[str, Any] = files if files is not None else {}
        cleaned, errors = cls._clean_fields(raw, files_map, only_present=False)

        if errors:
            return Invalid(errors=errors, raw=raw)

        instance = cls(**cleaned)

        # Cross-field hook.
        extra_errors: dict[str, list[str]] | None
        try:
            extra_errors = instance.check(context=context)
        except ValidationError as e:
            if hasattr(e, "error_dict"):
                # dict(ValidationError) flattens error_dict to {field: [messages]}.
                extra_errors = dict(e)  # ty: ignore[no-matching-overload]
            else:
                extra_errors = {NON_FIELD_ERRORS: list(e.messages)}

        if extra_errors:
            return Invalid(errors=dict(extra_errors), raw=raw)

        return instance

    @classmethod
    def validate_partial(
        cls,
        data: dict[str, Any] | None,
        *,
        files: Any = None,
    ) -> Invalid | None:
        """Validate only the fields present in `data`/`files`.

        Returns `Invalid` if any present field failed, or `None` if they
        all passed. Fields absent from the input are skipped — no
        required-errors — and the cross-field `check()` hook does not run
        (it can't judge a subset).

        For HTMX live validation, where each keystroke posts one field and
        you only need "is what was sent OK so far":

            def htmx_post_validate(self):
                result = TaskSchema.validate_partial(self.request.form_data)
                if result is not None:
                    return JsonResponse(
                        {"valid": False, "errors": result.errors}
                    )
                return JsonResponse({"valid": True})

        Unlike `validate()`, this never returns a schema instance — a
        partially-checked payload can't produce a complete, safe-to-use one.
        """
        raw = data or {}
        files_map: dict[str, Any] = files if files is not None else {}
        _cleaned, errors = cls._clean_fields(raw, files_map, only_present=True)
        if errors:
            return Invalid(errors=errors, raw=raw)
        return None
