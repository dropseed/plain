from __future__ import annotations

from typing import Any, ClassVar, Literal, Self

from plain.exceptions import NON_FIELD_ERRORS, ValidationError
from plain.utils.hashable import make_hashable

from .fields import Field, FileField
from .result import Error, Invalid

__all__ = ("Form",)

# Marks a field with no value on an instance — distinct from a field that
# legitimately cleaned to None. A `validate()` instance always has every
# field set, but one built directly (`Form(**partial_data)`) can leave
# fields unset. __repr__/__eq__/__hash__ use this so an unset field never
# compares or hashes equal to a real None.
_UNSET = object()


def _leaf_to_error(leaf: ValidationError, field: str | None) -> Error:
    """Build an `Error` from a single (leaf) `ValidationError`."""
    message = leaf.message
    if leaf.params:
        message %= leaf.params
    return Error(message=str(message), code=leaf.code or "invalid", field=field)


def _errors_from_exception(
    exc: ValidationError, *, field: str | None = None
) -> list[Error]:
    """Flatten a raised `ValidationError` into a flat list of `Error`s.

    A field's `clean()` raises errors that all belong to one field, named
    by `field`. A `check()` override may instead raise a dict-shaped
    `ValidationError` keyed by field name — there each key supplies the
    field, and the `"__all__"` key maps to a form-level error (`field=None`).
    """
    if hasattr(exc, "error_dict"):
        errors: list[Error] = []
        for key, leaves in exc.error_dict.items():
            key_field = None if key == NON_FIELD_ERRORS else key
            errors.extend(_leaf_to_error(leaf, key_field) for leaf in leaves)
        return errors
    return [_leaf_to_error(leaf, field) for leaf in exc.error_list]


class Form:
    """Pure validating parser.

    Subclass and declare each field as `name = types.*(...)`:

        from plain.forms import Form, types

        class ContactForm(Form):
            email = types.EmailField()
            message = types.TextField(max_length=2000)

    Each field is a descriptor: `ContactForm.email` is the typed
    `Field[str]` reference, `result.email` the cleaned `str` value. The
    `types.*` constructors are typed, so both faces are statically
    checked with no annotation to write.

    Validate a dict and branch on the result. `Form.validate()` returns
    either an instance of the form (success — truthy) or `Invalid`
    (failure — falsy):

        result = ContactForm.validate(data)
        if not result:
            return ...                # handle errors — result is Invalid
        # result is the typed form instance — no `.data` indirection
        result.email                  # str

    Override `check()` (instance method) for cross-field validation that
    runs after fields have cleaned successfully.
    """

    # Populated by __init_subclass__; the empty default is for type-checker
    # visibility and covers `Form` itself, which declares no fields.
    _form_fields: ClassVar[dict[str, Field[Any]]] = {}

    def __init_subclass__(cls, **kwargs: Any) -> None:
        """Collect the `Field` instances declared on the class into `_form_fields`.

        Field declarations look like `email = EmailField()`. Each field
        is a descriptor that stays on the class — `Form.email` is the
        typed reference, `instance.email` the cleaned value — so this just
        gathers them into one ordered map for validation to walk, merging in
        any fields inherited from base classes.
        """
        super().__init_subclass__(**kwargs)
        fields: dict[str, Field[Any]] = {}
        for base in cls.__bases__:
            base_fields = getattr(base, "_form_fields", None)
            if base_fields:
                fields.update(base_fields)
        for key, value in vars(cls).items():
            if isinstance(value, Field):
                fields[key] = value
        cls._form_fields = fields

    @classmethod
    def fields(cls) -> dict[str, Field[Any]]:
        """The declared fields as an ordered ``name -> Field`` map.

        The public introspection surface — walk this to render a form,
        document it, or drive tooling, without needing a validated
        instance. Returns a copy; the live mapping is internal.
        """
        return dict(cls._form_fields)

    def __init__(self, **data: Any) -> None:
        for name in self._form_fields:
            if name in data:
                object.__setattr__(self, name, data[name])
        object.__setattr__(self, "_frozen", True)

    def __setattr__(self, name: str, value: Any) -> None:
        # Forms are frozen after construction. Mutating a validated
        # instance defeats the contract — `result.email` is supposed to
        # carry the cleaned value, not whatever someone assigned later.
        if getattr(self, "_frozen", False):
            raise AttributeError(
                f"{type(self).__name__} is frozen — form instances are "
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
        for k in self._form_fields:
            value = getattr(self, k, _UNSET)
            parts.append(f"{k}=<unset>" if value is _UNSET else f"{k}={value!r}")
        return f"{type(self).__name__}({', '.join(parts)})"

    def __eq__(self, other: object) -> bool:
        if type(self) is not type(other):
            return NotImplemented
        return all(
            getattr(self, k, _UNSET) == getattr(other, k, _UNSET)
            for k in self._form_fields
        )

    def __hash__(self) -> int:
        # make_hashable converts list-valued fields (e.g. MultipleChoiceField)
        # into tuples so form instances stay hashable. _UNSET marks a field
        # with no value — it hashes distinctly from a real None.
        values = tuple(getattr(self, k, _UNSET) for k in self._form_fields)
        return hash(make_hashable(values))

    def __bool__(self) -> Literal[True]:
        """Always truthy — a `Form` instance is the success result.
        `Invalid` is the falsy counterpart, so a view branches with
        `if not result:` rather than an `isinstance` check."""
        return True

    def check(self) -> list[Error] | None:
        """Cross-field validation hook. Override in subclasses.

        Runs after every field has cleaned successfully; `self` is the
        typed instance with all cleaned values set, so an override gets
        full type-checker support without a Liskov violation.

        Sees only the form's own fields. Validation that needs request or
        database state — the current user, a uniqueness check — is the
        caller's job, kept out of the form so it stays a pure parser.

        The contract is return-based, matching `validate()`: return a list
        of `Error`s — set each one's `field` to the field it concerns, or
        leave it `None` for a form-level error — or `None` when nothing is
        wrong. Don't raise — a form is a non-raising parser, and its
        cross-field hook follows suit.

        (A `ValidationError` raised here is still caught and folded into the
        result rather than escaping, but returning is the documented way.)
        """
        return None

    @classmethod
    def _clean_fields(
        cls,
        raw: Any,
        files_map: dict[str, Any],
    ) -> tuple[dict[str, Any], list[Error]]:
        """Run each declared field's `clean` against `raw`/`files_map`.

        Returns `(cleaned, errors)`. A field absent from the input is
        cleaned with `None`, surfacing its required-error.
        """
        cleaned: dict[str, Any] = {}
        errors: list[Error] = []
        # MultiValueDict carries multi-valued keys; plain dicts don't. For
        # multi-select fields we need to pull all values, not just the last.
        is_multi_value_dict = hasattr(raw, "getlist")

        for name, field in cls._form_fields.items():
            try:
                if isinstance(field, FileField):
                    # FileField.clean takes (data, initial).
                    cleaned[name] = field.clean(files_map.get(name), None)
                elif is_multi_value_dict and field.multi_value:
                    # `raw` has .getlist (verified by the is_multi_value_dict guard).
                    cleaned[name] = field.clean(raw.getlist(name))
                else:
                    cleaned[name] = field.clean(raw.get(name))
            except ValidationError as e:
                errors.extend(_errors_from_exception(e, field=name))

        return cleaned, errors

    @classmethod
    def validate(
        cls,
        data: dict[str, Any] | None,
        *,
        files: Any = None,
    ) -> Self | Invalid:
        """Validate `data` against this form.

        Returns either an instance of `cls` (cleaned, typed values set as
        attributes) or `Invalid` (a list of `Error`s). Never raises on
        validation failure. A returned instance means *every* declared
        field validated and `check()` passed — `result.<field>` is always
        safe, there is no half-populated instance.

        For file uploads, pass `request.files` (a `MultiValueDict[str,
        UploadedFile]`) as `files=`. `FileField`/`ImageField` declarations
        are populated from `files` instead of `data`; everything else
        reads from `data` as usual.
        """
        raw = data or {}
        files_map: dict[str, Any] = files if files is not None else {}
        cleaned, errors = cls._clean_fields(raw, files_map)

        if errors:
            return Invalid(errors=errors, raw=raw)

        instance = cls(**cleaned)

        # Cross-field hook.
        extra_errors: list[Error] | None
        try:
            extra_errors = instance.check()
        except ValidationError as e:
            extra_errors = _errors_from_exception(e)

        if extra_errors:
            return Invalid(errors=extra_errors, raw=raw)

        return instance
