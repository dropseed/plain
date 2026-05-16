"""ModelSchema — auto-derive Schema fields from a `postgres.Model`.

The Schema-shaped equivalent of `plain.postgres.forms.ModelForm`: declare a
`model` plus annotations, and `__init_subclass__` derives a validating field
per annotation — scalar columns map to `types.*` fields, a ForeignKey becomes
a `ModelChoiceField`, a ManyToMany becomes a `ModelMultipleChoiceField`.

Like `SchemaFormView`, this lives in `plain.schema` for now — even though it makes
the package depend on `plain.postgres` — so the schema/model design can be
iterated on in one place. It's imported from this module directly (`from
plain.schema.modelschema import ModelSchema`) and not re-exported at the
package top level, so a plain `from plain.schema import Schema` doesn't load
the ORM.

Per-request queryset scoping (the multi-tenant FK/M2M case) is done by
`with_querysets()`, which returns a subclass whose relation fields are
narrowed — that scoped class drives both validation and the rendered
`<select>` options.
"""

from __future__ import annotations

from itertools import chain
from typing import Any, ClassVar, Self, cast

from plain.exceptions import ValidationError

from . import fields as schema_fields
from .fields import EMPTY_VALUES, Field
from .schema import Schema

__all__ = (
    "ModelChoiceField",
    "ModelMultipleChoiceField",
    "ModelSchema",
    "modelfield_to_schemafield",
)


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
        return type(self)(queryset, required=self.required, initial=self.initial)

    @property
    def choices(self) -> list[tuple[Any, str]]:
        """`(id, label)` pairs for rendering a `<select>`."""
        return [(obj.id, str(obj)) for obj in self.queryset]


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


def modelfield_to_schemafield(modelfield: Any) -> Field[Any] | None:
    """Map a postgres model field to a schema field instance, or `None` for
    fields that can't be derived (the primary key, non-column fields)."""
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

    # `create_now`/`generate`/`update_now` columns fill themselves in, so the
    # schema must let the caller omit them.
    auto_filled = modelfield.db_returning or modelfield.auto_fills_on_save
    required = modelfield.required and not auto_filled
    initial = (
        modelfield.get_default()
        if isinstance(modelfield, DefaultableField)
        and modelfield.has_default()
        and not auto_filled
        else None
    )

    if isinstance(modelfield, ChoicesField) and modelfield.choices is not None:
        return schema_fields.TypedChoiceField(
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
        # never "required" at the schema layer.
        return schema_fields.BooleanField(required=False, initial=initial)

    if isinstance(modelfield, postgres.DecimalField):
        return schema_fields.DecimalField(
            max_digits=modelfield.max_digits,
            decimal_places=modelfield.decimal_places,
            required=required,
            initial=initial,
        )

    if isinstance(modelfield, postgres.TextField):
        return schema_fields.TextField(
            max_length=modelfield.max_length, required=required, initial=initial
        )

    if isinstance(modelfield, postgres.JSONField):
        return schema_fields.JSONField(required=required, initial=initial)

    # A model field whose class name matches a schema field — e.g. a model
    # DateField or EmailField maps to the schema field of the same name.
    same_name = getattr(schema_fields, type(modelfield).__name__, None)
    if isinstance(same_name, type) and issubclass(same_name, Field):
        return same_name(required=required, initial=initial)

    return schema_fields.TextField(required=required, initial=initial)


def _auto_derive_fields(model: Any, annotation_names: list[str], cls: type) -> None:
    """Set an auto-derived Field on `cls` for each annotation that names a
    model field and doesn't already have a Field declared on the class body."""
    by_name = {
        f.name: f
        for f in chain(
            model._model_meta.concrete_fields, model._model_meta.many_to_many
        )
    }
    for fname in annotation_names:
        if fname == "model":
            continue
        if isinstance(cls.__dict__.get(fname), Field):
            continue  # user declared a Field explicitly — leave it
        if fname not in by_name:
            continue  # not a model field — a plain extra field, leave it
        derived = modelfield_to_schemafield(by_name[fname])
        if derived is not None:
            setattr(cls, fname, derived)


class ModelSchema(Schema):
    """Schema base class backed by a model.

    Subclass, set `model = X`, and annotate the fields to expose. Fields
    auto-derive from the model; override one by declaring a Field explicitly.
    """

    # `model` is set on subclasses; `__init_subclass__` copies it to
    # `_model_schema_model` (also following inheritance).
    model: ClassVar[Any] = None
    _model_schema_model: ClassVar[Any] = None

    def __init_subclass__(cls, **kwargs: Any) -> None:
        """Auto-derive fields from `model`, then collect them like any Schema."""
        model = cls.__dict__.get("model")
        annotations = cls.__dict__.get("__annotations__") or {}
        if model is not None and annotations:
            _auto_derive_fields(model, list(annotations), cls)
        # Schema.__init_subclass__ collects every Field on the class — the
        # ones just derived included — into `_schema_fields`.
        super().__init_subclass__(**kwargs)
        if model is None:
            for base in cls.__bases__:
                inherited = getattr(base, "model", None)
                if inherited is not None:
                    model = inherited
                    break
        cls._model_schema_model = model

    @classmethod
    def with_querysets(cls, **querysets: Any) -> type[Self]:
        """Return a subclass with FK/M2M querysets narrowed.

        Use for owner-scoped multi-tenant input: the scoped class drives both
        validation and the rendered `<select>` options, so a user can neither
        pick nor see another tenant's rows.
        """
        valid = {
            fname
            for fname, field in cls._schema_fields.items()
            if isinstance(field, ModelChoiceField | ModelMultipleChoiceField)
        }
        unknown = set(querysets) - valid
        if unknown:
            raise TypeError(
                f"{cls.__name__}.with_querysets() got unknown field(s) "
                f"{sorted(unknown)}; valid FK/M2M fields: {sorted(valid)}"
            )

        scoped_fields: dict[str, Field[Any]] = {}
        for fname, field in cls._schema_fields.items():
            if fname in querysets:
                # Only FK/M2M fields land here (the `unknown` check above).
                field = field._with_queryset(querysets[fname])  # ty: ignore[unresolved-attribute]
            scoped_fields[fname] = field

        scoped = cast(
            type[Self],
            type(f"{cls.__name__}Scoped", (cls,), {"__annotations__": {}}),
        )
        scoped._schema_fields = scoped_fields
        return scoped

    def save(self, instance: Any = None) -> Any:
        """Apply the validated values to a model instance and persist it.

        Pass an existing instance to update a row, or omit it to build a fresh
        one from `model = ...`. Scalar and FK values are set, the row is
        saved, then M2M relations are assigned (they need a primary key).
        """
        if instance is None:
            model = type(self)._model_schema_model
            if model is None:
                raise TypeError(
                    f"{type(self).__name__}.save() needs `model = ...` set, "
                    f"or an explicit instance."
                )
            instance = model()

        m2m: list[tuple[str, Any]] = []
        for fname, field in type(self)._schema_fields.items():
            if not hasattr(self, fname):
                continue
            value = getattr(self, fname)
            if isinstance(field, ModelMultipleChoiceField):
                m2m.append((fname, value))
            else:
                setattr(instance, fname, value)

        instance.save()

        for fname, value in m2m:
            getattr(instance, fname).set(list(value))

        return instance
