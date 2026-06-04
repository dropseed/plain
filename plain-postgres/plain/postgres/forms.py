"""ModelForm — a `Form` whose fields are declared from postgres model columns.

Declare each field with `model_field(Model.column)`; it copies the column's
type, validators, and constraints into a `plain.forms` field. A scalar column
maps to the matching `plain.forms` field, a ForeignKey to a `ModelChoiceField`,
a ManyToMany to a `ModelMultipleChoiceField`.

`ModelForm` does not persist — it validates like any `Form`. To write a
validated result back to the database, the `create_from()` / `update_from()`
functions here consume it.

`with_querysets()` scopes FK/M2M choices per request (the multi-tenant case);
`initial_from()` builds an edit form's initial values from a model instance.
"""

from __future__ import annotations

from itertools import chain
from typing import TYPE_CHECKING, Any, Self, cast, overload

from plain.exceptions import ValidationError
from plain.forms import Form
from plain.forms import fields as form_fields
from plain.forms.fields import EMPTY_VALUES, Field

if TYPE_CHECKING:
    from plain.postgres.base import Model
    from plain.postgres.fields.related_managers import ManyToManyManager

__all__ = [
    "ModelChoiceField",
    "ModelForm",
    "ModelMultipleChoiceField",
    "create_from",
    "model_field",
    "update_from",
]


class _ModelChoiceBase(Field[Any]):
    """Shared queryset handling for ModelChoiceField and ModelMultipleChoiceField."""

    def __init__(
        self, queryset: Any, *, required: bool = True, initial: Any = None
    ) -> None:
        super().__init__(required=required, initial=initial)
        self.queryset = queryset

    def _to_id(self, value: Any) -> Any:
        """Normalize a model instance to its primary key; pass other values through."""
        if isinstance(value, self.queryset.model):
            return value.id
        return value

    def _with_queryset(self, queryset: Any) -> Self:
        """A copy of this field bound to a different (e.g. owner-scoped) queryset."""
        clone = type(self)(queryset, required=self.required, initial=self.initial)
        clone.name = self.name
        return clone

    @property
    def choices(self) -> list[tuple[Any, str]]:
        """`(id, label)` pairs for rendering a `<select>`."""
        # `.all()` clones the queryset — iterating `self.queryset` would
        # populate a shared `_result_cache` on the class-level field instance
        # and return stale rows on every later render.
        return [(obj.id, str(obj)) for obj in self.queryset.all()]


class ModelChoiceField(_ModelChoiceBase):
    """Validates a primary key against a model queryset, cleaning to the
    matching model instance."""

    def clean(self, value: Any) -> Any:
        if value in EMPTY_VALUES:
            if self.required:
                raise ValidationError("This field is required.", code="required")
            return None
        try:
            return self.queryset.get(id=self._to_id(value))
        except (self.queryset.model.DoesNotExist, ValueError, TypeError):
            raise ValidationError(
                "Select a valid choice. That choice is not one of the "
                "available choices.",
                code="invalid_choice",
            )

    @property
    def choices(self) -> list[tuple[Any, str]]:
        # A blank option leads when the field is optional.
        blank: list[tuple[Any, str]] = [] if self.required else [("", "---------")]
        return blank + super().choices


class ModelMultipleChoiceField(_ModelChoiceBase):
    """Validates a list of primary keys against a model queryset, cleaning to
    a list of model instances."""

    multi_value = True

    def __init__(
        self, queryset: Any, *, required: bool = False, initial: Any = None
    ) -> None:
        # M2M relations are conventionally optional.
        super().__init__(queryset, required=required, initial=initial)

    def clean(self, value: Any) -> list[Any]:
        if not value:
            if self.required:
                raise ValidationError("This field is required.", code="required")
            return []
        if not isinstance(value, list | tuple):
            raise ValidationError("Enter a list of values.", code="invalid_list")
        ids = [self._to_id(item) for item in value]
        objects = list(self.queryset.filter(id__in=ids))
        found = {str(obj.id) for obj in objects}
        for item in ids:
            if str(item) not in found:
                raise ValidationError(
                    f"Select a valid choice. {item} is not one of the "
                    "available choices.",
                    code="invalid_choice",
                )
        return objects


def _modelfield_to_formfield(modelfield: Any) -> Field[Any] | None:
    """Map a postgres model field to a form field instance, or `None` when
    the column isn't user input: the primary key, a non-column field, or a
    column the database fills itself (`generate`/`create_now`/`update_now`)."""
    from plain import postgres
    from plain.postgres.fields import ChoicesField
    from plain.postgres.fields.base import ColumnField, DefaultableField
    from plain.postgres.fields.related import ManyToManyField

    if isinstance(modelfield, ManyToManyField):
        return ModelMultipleChoiceField(
            queryset=modelfield.remote_field.model.query,
            required=False,
        )

    if not isinstance(modelfield, ColumnField):
        return None
    if isinstance(modelfield, postgres.PrimaryKeyField):
        return None
    # A column the database fills itself is never user input — keep it off
    # the form so a blank submission can't fight the database default.
    if modelfield.db_returning or modelfield.auto_fills_on_save:
        return None

    required = modelfield.required
    initial = (
        modelfield.get_default()
        if isinstance(modelfield, DefaultableField) and modelfield.has_default()
        else None
    )

    if isinstance(modelfield, ChoicesField) and modelfield.choices is not None:
        return form_fields.TypedChoiceField(
            choices=modelfield.get_choices(include_blank=not required),
            coerce=modelfield.to_python,
            required=required,
            initial=initial,
        )

    if isinstance(modelfield, postgres.ForeignKeyField):
        return ModelChoiceField(
            queryset=modelfield.remote_field.model.query,
            required=required,
            initial=initial,
        )

    if isinstance(modelfield, postgres.BooleanField):
        # An HTML checkbox omits itself when unchecked, so a boolean column is
        # never "required" at the form layer.
        return form_fields.BooleanField(required=False, initial=initial)

    if isinstance(modelfield, postgres.DecimalField):
        return form_fields.DecimalField(
            max_digits=modelfield.max_digits,
            decimal_places=modelfield.decimal_places,
            required=required,
            initial=initial,
        )

    if isinstance(modelfield, postgres.TextField):
        return form_fields.TextField(
            max_length=modelfield.max_length, required=required, initial=initial
        )

    if isinstance(modelfield, postgres.JSONField):
        return form_fields.JSONField(required=required, initial=initial)

    # A model field whose class name matches a form field — e.g. a model
    # DateField or EmailField maps to the form field of the same name.
    same_name = getattr(form_fields, type(modelfield).__name__, None)
    if isinstance(same_name, type) and issubclass(same_name, Field):
        return same_name(required=required, initial=initial)

    return form_fields.TextField(required=required, initial=initial)


def _resolve_model_field(column: Any) -> Any:
    """Normalize a model-column reference to its underlying field.

    A scalar column accessed on the class (`Note.title`) is the field itself.
    A ForeignKey or ManyToMany installs a forward descriptor in its place;
    both wrap the field as `.field`.
    """
    from plain.postgres.fields.related_descriptors import (
        ForwardForeignKeyDescriptor,
        ForwardManyToManyDescriptor,
    )

    if isinstance(column, ForwardForeignKeyDescriptor | ForwardManyToManyDescriptor):
        return column.field
    return column


@overload
def model_field[M: Model](column: ManyToManyManager[M]) -> Field[list[M]]: ...
@overload
def model_field[T](column: T) -> Field[T]: ...
def model_field(column: Any) -> Field[Any]:
    """Declare a `ModelForm` field derived from a model column.

        class NoteForm(ModelForm):
            title = model_field(Note.title)
            body = model_field(Note.body)

    Pass the model column itself — `Note.title`. The form field's type,
    validators, and constraints are copied from it, so `result.title` is
    typed exactly as the column, and a column typo (`Note.titel`) is a type
    error. A ForeignKey becomes a `ModelChoiceField`, a ManyToMany a
    `ModelMultipleChoiceField`.

    The primary key and database-filled columns (`generate`/`create_now`)
    aren't user input; `model_field` rejects them — declare such a field
    explicitly with a `types.*` field if a form genuinely needs it.
    """
    modelfield = _resolve_model_field(column)
    derived = _modelfield_to_formfield(modelfield)
    if derived is None:
        raise TypeError(
            f"{modelfield!r} can't be derived into a form field — declare the "
            f"field explicitly with a `types.*` field instead."
        )
    return derived


class ModelForm(Form):
    """A `Form` whose fields are declared from postgres model columns.

    Declare each field with `model_field(Model.column)`. `ModelForm` adds two
    model-aware helpers to `Form` — `with_querysets()` and `initial_from()` —
    but does not itself persist: the `create_from()` and `update_from()`
    functions write a validated result to the database.
    """

    @classmethod
    def with_querysets(cls, **querysets: Any) -> type[Self]:
        """Return a subclass with FK/M2M querysets narrowed.

        Use for owner-scoped multi-tenant input: the scoped class drives both
        validation and the rendered `<select>` options, so a user can neither
        pick nor see another tenant's rows.
        """
        valid = {
            fname
            for fname, field in cls._form_fields.items()
            if isinstance(field, ModelChoiceField | ModelMultipleChoiceField)
        }
        unknown = set(querysets) - valid
        if unknown:
            raise TypeError(
                f"{cls.__name__}.with_querysets() got unknown field(s) "
                f"{sorted(unknown)}; valid FK/M2M fields: {sorted(valid)}"
            )

        scoped_fields: dict[str, Field[Any]] = {}
        for fname, field in cls._form_fields.items():
            if fname in querysets:
                # Only FK/M2M fields land here (the `unknown` check above).
                field = field._with_queryset(querysets[fname])  # ty: ignore[unresolved-attribute]
            scoped_fields[fname] = field

        scoped = cast(type[Self], type(f"{cls.__name__}Scoped", (cls,), {}))
        scoped._form_fields = scoped_fields
        return scoped

    @classmethod
    def initial_from(cls, instance: Any) -> dict[str, Any]:
        """Build an initial-values dict from a model instance.

        Translates a ForeignKey to its related object's id and a ManyToMany
        relation to a list of related-object ids — what `ModelChoiceField`
        and `ModelMultipleChoiceField` take as input. Scalar fields fall
        through to a plain `getattr`. Pass the result as `render_form`'s
        `values=` to pre-fill an edit form.
        """
        initial: dict[str, Any] = {}
        for fname, field in cls._form_fields.items():
            if isinstance(field, ModelMultipleChoiceField):
                related = getattr(instance, fname, None)
                initial[fname] = (
                    [] if related is None else [obj.id for obj in related.query]
                )
            elif isinstance(field, ModelChoiceField):
                # A foreign key returns a partial related object whose `.id` is
                # query-free; there is no `<name>_id` attribute to read.
                related = getattr(instance, fname, None)
                initial[fname] = None if related is None else related.id
            else:
                initial[fname] = getattr(instance, fname, None)
        return initial


def _apply_result[T: Model](
    instance: T, result: ModelForm
) -> tuple[T, list[tuple[str, Any]]]:
    """Set a validated `ModelForm` result's column and FK values onto the instance.

    Returns the instance plus the deferred M2M assignments — those need a
    primary key, so the caller applies them after the row is written. Form
    fields that aren't columns of the instance's model are ignored — a
    `ModelForm` may carry an extra non-model field (e.g. a confirm-password).
    """
    columns = {
        f.name: f
        for f in chain(
            instance._model_meta.concrete_fields,
            instance._model_meta.many_to_many,
        )
    }

    m2m: list[tuple[str, Any]] = []
    for fname, field in type(result).fields().items():
        if fname not in columns:
            continue
        value = getattr(result, fname)
        if isinstance(field, ModelMultipleChoiceField):
            m2m.append((fname, value))
            continue
        # Skip empty submissions for DB-filled columns (generate/create_now)
        # so the DATABASE_DEFAULT sentinel survives and Postgres produces it.
        column = columns[fname]
        if value in EMPTY_VALUES and (column.db_returning or column.auto_fills_on_save):
            continue
        setattr(instance, fname, value)

    return instance, m2m


def update_from[T: Model](instance: T, result: ModelForm) -> T:
    """Apply a validated `ModelForm` result onto a persisted instance and UPDATE it.

    Sets the column and FK values, UPDATEs the existing row, then assigns the
    M2M relations (which need a primary key first). Returns the instance.
    """
    instance, m2m = _apply_result(instance, result)

    instance.update()

    for fname, value in m2m:
        getattr(instance, fname).set(list(value))

    return instance


def create_from[T: Model](model: type[T], result: ModelForm, /, **extra: Any) -> T:
    """Create a new model instance from a validated `ModelForm` result and INSERT it.

    Column values come from `result`; `extra` kwargs (e.g. `author=user`)
    populate columns the form doesn't carry. Returns the inserted instance.
    """
    instance, m2m = _apply_result(model(**extra), result)

    instance.create()

    for fname, value in m2m:
        getattr(instance, fname).set(list(value))

    return instance
