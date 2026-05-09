"""ModelSchema — auto-derive `plain.schema.Schema` fields from a model.

Equivalent in scope to `plain.postgres.forms.ModelForm` but Schema-shaped:
returns a typed schema instance, no `cleaned_data` indirection, no
`Form(request=...)` ceremony, no Liskov-warning hooks.

User declares:

    class ContactSchema(ModelSchema):
        model = Contact

        email: str
        name: str
        phone: str | None

The `model` class attribute names the model. Annotations name the fields
to expose — no separate `fields = (...)` list. The type checker sees the
attributes; the metaclass auto-derives the Field implementation from the
model unless the user provides one explicitly.

For per-request queryset scoping (multi-tenant FK/M2M), pass
`context["querysets"]` to `validate()`:

    result = TaskSchema.validate(
        request.json_data,
        context={"querysets": {
            "project": Project.query.filter(owner=user),
            "tags": Tag.query.filter(owner=user),
        }},
    )
"""

from __future__ import annotations

import copy
from itertools import chain
from typing import Any, ClassVar, cast

from plain.forms.fields import Field
from plain.schema import Invalid, Schema
from plain.schema.schema import SchemaMeta

from .fields.related import ManyToManyField
from .forms import (
    ModelChoiceField,
    ModelMultipleChoiceField,
    modelfield_to_formfield,
)

__all__ = (
    "Invalid",
    "ModelChoiceField",
    "ModelMultipleChoiceField",
    "ModelSchema",
    "modelfield_to_schemafield",
)


def modelfield_to_schemafield(modelfield: Any) -> Field | None:
    """Map a model field to a schema field instance.

    Reuses `modelfield_to_formfield` for column-backed fields and adds
    explicit handling for relational fields:
      * ForeignKeyField → ModelChoiceField (via modelfield_to_formfield)
      * ManyToManyField → ModelMultipleChoiceField (special-cased here
        because M2M is not a ColumnField).
    """
    if isinstance(modelfield, ManyToManyField):
        related = modelfield.remote_field.model
        return ModelMultipleChoiceField(
            queryset=related.query,
            required=False,  # M2M is conventionally optional
        )

    return modelfield_to_formfield(modelfield)


class ModelSchemaMeta(SchemaMeta):
    """Schema metaclass that auto-derives Field instances from a model.

    The user declares:
      * `model = X` — the postgres.Model class as a class attribute
      * Annotations naming the fields from the model to expose

    The metaclass walks the class annotations, looks up each name on the
    model, and emits an appropriate Field instance unless the user has
    already provided one explicitly.
    """

    def __new__(
        mcs: type[ModelSchemaMeta],
        name: str,
        bases: tuple[type, ...],
        namespace: dict[str, Any],
    ) -> type:
        model = namespace.get("model")
        annotations = namespace.get("__annotations__") or {}

        if model is not None and annotations:
            _auto_derive_fields(model, list(annotations), namespace)

        new_cls = super().__new__(mcs, name, bases, namespace)
        # Inherit `model` from base if not declared on this class.
        if model is None:
            for base in bases:
                inherited = getattr(base, "model", None)
                if inherited is not None:
                    model = inherited
                    break
        setattr(new_cls, "_model_schema_model", model)

        # Validate user-declared `Querysets` TypedDict (if any) against the
        # FK/M2M fields. Catches typos at class-creation time so they don't
        # silently pass through `validate(context={"querysets": {...}})`.
        querysets_dict = namespace.get("Querysets")
        if querysets_dict is not None:
            _validate_querysets_typeddict(name, new_cls, querysets_dict)

        return new_cls


def _validate_querysets_typeddict(
    schema_name: str, cls: type, querysets_dict: Any
) -> None:
    """Ensure a user-declared `Querysets` TypedDict's keys match the schema's
    FK/M2M field names. Extra or misspelled keys raise at class-creation time.
    """
    declared_keys = set(getattr(querysets_dict, "__annotations__", {}).keys())
    if not declared_keys:
        return
    valid_keys = {
        fname
        for fname, field in cls._schema_fields.items()  # ty: ignore[unresolved-attribute]
        if isinstance(field, ModelChoiceField | ModelMultipleChoiceField)
    }
    unknown = declared_keys - valid_keys
    if unknown:
        raise TypeError(
            f"{schema_name}.Querysets has unknown keys: {sorted(unknown)}. "
            f"Valid FK/M2M field names: {sorted(valid_keys)}"
        )


def _auto_derive_fields(
    model: type,
    annotation_names: list[str],
    namespace: dict[str, Any],
) -> None:
    """Populate `namespace[name]` with auto-derived Field instances for any
    annotation that doesn't already have a Field declared. Annotations that
    aren't on the model are left for plain Schema handling (e.g. extra
    fields like `confirm_password` that the user adds)."""
    model_meta = model._model_meta  # ty: ignore[unresolved-attribute]
    by_name = {
        f.name: f for f in chain(model_meta.concrete_fields, model_meta.many_to_many)
    }

    for fname in annotation_names:
        # Reserved metaclass-handled names — skip.
        if fname == "model":
            continue
        if fname in namespace and isinstance(namespace[fname], Field):
            # User explicitly declared a Field — leave it alone.
            continue
        if fname not in by_name:
            # Annotation isn't a model field; let the user keep it as a
            # regular Schema field (they must provide their own Field).
            continue
        schema_field = modelfield_to_schemafield(by_name[fname])
        if schema_field is not None:
            namespace[fname] = schema_field


class ModelSchema(Schema, metaclass=ModelSchemaMeta):
    """Schema base class for models.

    Subclass and define `model = X` plus annotations for the fields you
    want exposed. Field instances auto-derive from the model; override
    by providing a Field instance explicitly:

        class ContactSchema(ModelSchema):
            model = Contact

            email: str
            name: str = types.TextField(min_length=2)  # stricter than model
    """

    # Set by ModelSchemaMeta from the `model` class attribute.
    _model_schema_model: ClassVar[type | None] = None

    # The `model` slot itself — declared here for documentation; set on
    # subclasses.
    model: ClassVar[type | None] = None

    @classmethod
    def validate(
        cls,
        data: dict[str, Any] | None,
        *,
        files: Any = None,
        context: dict[str, Any] | None = None,
        partial: bool = False,
    ) -> Any:
        """Validate, with per-request queryset substitution for FK/M2M fields.

        If `context["querysets"][field_name]` is set, it overrides the
        auto-derived queryset for that ModelChoiceField. Used for
        owner-scoped multi-tenant validation.
        """
        querysets = (context or {}).get("querysets") or {}
        if querysets:
            _check_querysets_keys(cls, querysets)
        target_cls = _with_substituted_querysets(cls, querysets) if querysets else cls
        # Call Schema.validate's underlying function bound to the (possibly
        # substituted) class, bypassing ModelSchema.validate to avoid recursion.
        return Schema.validate.__func__(
            target_cls, data, files=files, context=context, partial=partial
        )

    @classmethod
    def initial_from(cls, instance: Any) -> dict[str, Any]:
        """Build an `initial=` dict from a model instance.

        Translates FK fields to their `_id` value (what `ModelChoiceField`
        renders) and M2M relations to a list of related-object ids (what
        `ModelMultipleChoiceField` renders). Other fields fall through to
        a plain `getattr`.
        """
        initial: dict[str, Any] = {}
        for fname, field in cls._schema_fields.items():
            if isinstance(field, ModelMultipleChoiceField):
                related = getattr(instance, fname, None)
                if related is None:
                    initial[fname] = []
                else:
                    initial[fname] = [str(o.id) for o in related.query]
            elif isinstance(field, ModelChoiceField):
                initial[fname] = getattr(instance, f"{fname}_id", None)
            else:
                initial[fname] = getattr(instance, fname, None)
        return initial

    def save(self, instance: Any = None) -> Any:
        """Apply validated values to a model instance and persist.

        With `instance=None` (default), constructs a fresh instance from
        the schema's `model` and saves it. Pass an existing instance to
        update an existing row.

        Scalar + FK fields are applied with `setattr`, then `instance.save()`
        runs, then M2M relationships are set (they need the instance to
        have a primary key).
        """
        if instance is None:
            model = type(self)._model_schema_model
            if model is None:
                raise TypeError(
                    f"{type(self).__name__}.save() requires `model = ...` "
                    f"to be set, or pass an explicit instance."
                )
            instance = model()

        m2m_assignments: list[tuple[str, Any]] = []
        for fname, field in type(self)._schema_fields.items():
            if not hasattr(self, fname):
                continue
            value = getattr(self, fname)
            if isinstance(field, ModelMultipleChoiceField):
                m2m_assignments.append((fname, value))
                continue
            setattr(instance, fname, value)

        instance.save()

        for fname, value in m2m_assignments:
            getattr(instance, fname).set(list(value))

        return instance


def _check_querysets_keys(
    schema_class: type[ModelSchema], querysets: dict[str, Any]
) -> None:
    """Raise if `querysets` has keys that aren't FK/M2M fields on the schema.

    Without this, a typo in `context={"querysets": {"projectt": ...}}` would
    silently fail to substitute and the request would scope against the
    default queryset — a hard-to-debug data-leak class of bug.
    """
    valid_keys = {
        fname
        for fname, field in schema_class._schema_fields.items()
        if isinstance(field, ModelChoiceField | ModelMultipleChoiceField)
    }
    unknown = set(querysets) - valid_keys
    if unknown:
        raise TypeError(
            f"{schema_class.__name__}.validate(context={{'querysets': ...}}) "
            f"has unknown keys: {sorted(unknown)}. "
            f"Valid FK/M2M field names: {sorted(valid_keys)}"
        )


def _with_substituted_querysets(
    schema_class: type[ModelSchema],
    querysets: dict[str, Any],
) -> type[ModelSchema]:
    """Return a Schema subclass with per-field querysets substituted.

    Doesn't mutate the original — clones each affected field via copy.copy
    so concurrent requests with different querysets don't interfere.
    """
    needs_substitution = any(name in schema_class._schema_fields for name in querysets)
    if not needs_substitution:
        return schema_class

    new_fields: dict[str, Field] = {}
    for name, field in schema_class._schema_fields.items():
        if name in querysets and isinstance(field, ModelChoiceField):
            cloned = copy.copy(field)
            cloned.queryset = querysets[name]
            new_fields[name] = cloned
        else:
            new_fields[name] = field

    sub = cast(
        type[ModelSchema],
        ModelSchemaMeta(
            f"{schema_class.__name__}_Substituted",
            (schema_class,),
            {"__annotations__": {}},
        ),
    )
    setattr(sub, "_schema_fields", new_fields)
    return sub
