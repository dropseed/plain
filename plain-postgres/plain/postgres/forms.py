"""Choice-field types and the model-field → schema-field dispatch
function used by `plain.postgres.modelschema`.

This module is the residual of the previous Form/ModelForm implementation.
The Form-based classes have been retired in favor of `plain.schema.Schema`
and `plain.postgres.modelschema.ModelSchema`. The remaining contents are
the FK/M2M choice fields and the dispatch function — both reused by
ModelSchema's auto-derive metaclass.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from plain.exceptions import ValidationError
from plain.forms import fields
from plain.forms.fields import ChoiceField, Field
from plain.postgres.fields import ChoicesField
from plain.postgres.fields.base import ColumnField, DefaultableField

if TYPE_CHECKING:
    from plain.postgres.fields import Field as ModelField

__all__ = (
    "ModelChoiceField",
    "ModelMultipleChoiceField",
    "modelfield_to_formfield",
)


class ModelChoiceIteratorValue:
    def __init__(self, value: Any, instance: Any) -> None:
        self.value = value
        self.instance = instance

    def __str__(self) -> str:
        return str(self.value)

    def __hash__(self) -> int:
        return hash(self.value)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, ModelChoiceIteratorValue):
            other = other.value
        return self.value == other


class ModelChoiceIterator:
    def __init__(self, field: ModelChoiceField) -> None:
        self.field = field
        self.queryset = field.queryset

    def __iter__(self) -> Any:
        if self.field.empty_label is not None:
            yield ("", self.field.empty_label)
        queryset = self.queryset
        # Can't use iterator() when queryset uses prefetch_related()
        if not queryset._prefetch_related_lookups:
            queryset = queryset.iterator()
        for obj in queryset:
            yield self.choice(obj)

    def __len__(self) -> int:
        # count() adds a query but uses less memory since the QuerySet results
        # won't be cached. In most cases, the choices will only be iterated on,
        # and __len__() won't be called.
        return self.queryset.count() + (1 if self.field.empty_label is not None else 0)

    def __bool__(self) -> bool:
        return self.field.empty_label is not None or self.queryset.exists()

    def choice(self, obj: Any) -> tuple[ModelChoiceIteratorValue, str]:
        return (
            ModelChoiceIteratorValue(self.field.prepare_value(obj), obj),
            str(obj),
        )


class ModelChoiceField(ChoiceField):
    """A ChoiceField whose choices are a model QuerySet."""

    # This class is a subclass of ChoiceField for purity, but it doesn't
    # actually use any of ChoiceField's implementation.
    default_error_messages = {
        "invalid_choice": "Select a valid choice. That choice is not one of the available choices.",
    }
    iterator = ModelChoiceIterator

    def __init__(
        self,
        queryset: Any,
        *,
        empty_label: str | None = "---------",
        required: bool = True,
        initial: Any = None,
        **kwargs: Any,
    ) -> None:
        # Call Field instead of ChoiceField __init__() because we don't need
        # ChoiceField.__init__().
        Field.__init__(
            self,
            required=required,
            initial=initial,
            **kwargs,
        )
        if required and initial is not None:
            self.empty_label = None
        else:
            self.empty_label = empty_label
        self.queryset = queryset

    def __deepcopy__(self, memo: dict[int, Any]) -> ModelChoiceField:
        result = super(ChoiceField, self).__deepcopy__(memo)
        # Need to force a new ModelChoiceIterator to be created.
        if self.queryset is not None:
            result.queryset = self.queryset.all()
        return result

    def _get_queryset(self) -> Any:
        return self._queryset

    def _set_queryset(self, queryset: Any) -> None:
        self._queryset = None if queryset is None else queryset.all()

    queryset = property(_get_queryset, _set_queryset)

    def _get_choices(self) -> ModelChoiceIterator:
        if hasattr(self, "_choices"):
            return self._choices  # ty: ignore[return-type]
        return self.iterator(self)

    choices = property(_get_choices, ChoiceField._set_choices)

    def prepare_value(self, value: Any) -> Any:
        if hasattr(value, "_model_meta"):
            return value.id
        return super().prepare_value(value)

    def to_python(self, value: Any) -> Any:
        if value in self.empty_values:
            return None
        try:
            key = "id"
            if isinstance(value, self.queryset.model):
                value = getattr(value, key)
            value = self.queryset.get(**{key: value})
        except (ValueError, TypeError, self.queryset.model.DoesNotExist):
            raise ValidationError(
                self.error_messages["invalid_choice"],
                code="invalid_choice",
                params={"value": value},
            )
        return value

    def validate(self, value: Any) -> None:
        return Field.validate(self, value)

    def has_changed(self, initial: Any, data: Any) -> bool:
        initial_value = initial if initial is not None else ""
        data_value = data if data is not None else ""
        return str(self.prepare_value(initial_value)) != str(data_value)


class ModelMultipleChoiceField(ModelChoiceField):
    """A MultipleChoiceField whose choices are a model QuerySet."""

    default_error_messages = {
        "invalid_list": "Enter a list of values.",
        "invalid_choice": "Select a valid choice. %(value)s is not one of the available choices.",
        "invalid_id_value": "'%(id)s' is not a valid value.",
    }

    def __init__(self, queryset: Any, **kwargs: Any) -> None:
        super().__init__(queryset, empty_label=None, **kwargs)

    def to_python(self, value: Any) -> list[Any]:  # ty: ignore[invalid-method-override]
        if not value:
            return []
        return list(self._check_values(value))

    def clean(self, value: Any) -> Any:
        value = self.prepare_value(value)
        if self.required and not value:
            raise ValidationError(self.error_messages["required"], code="required")
        elif not self.required and not value:
            return self.queryset.none()
        if not isinstance(value, list | tuple):
            raise ValidationError(
                self.error_messages["invalid_list"],
                code="invalid_list",
            )
        qs = self._check_values(value)
        # Since this overrides the inherited ModelChoiceField.clean
        # we run custom validators here
        self.run_validators(value)
        return qs

    def _check_values(self, value: Any) -> Any:
        try:
            value = frozenset(value)
        except TypeError:
            raise ValidationError(
                self.error_messages["invalid_list"],
                code="invalid_list",
            )
        for id_val in value:
            try:
                self.queryset.filter(id=id_val)
            except (ValueError, TypeError):
                raise ValidationError(
                    self.error_messages["invalid_id_value"],
                    code="invalid_id_value",
                    params={"id": id_val},
                )
        qs = self.queryset.filter(id__in=value)
        ids = {str(o.id) for o in qs}
        for val in value:
            if str(val) not in ids:
                raise ValidationError(
                    self.error_messages["invalid_choice"],
                    code="invalid_choice",
                    params={"value": val},
                )
        return qs

    def prepare_value(self, value: Any) -> Any:
        if (
            hasattr(value, "__iter__")
            and not isinstance(value, str)
            and not hasattr(value, "_model_meta")
        ):
            prepare_value = super().prepare_value
            return [prepare_value(v) for v in value]
        return super().prepare_value(value)

    def has_changed(self, initial: Any, data: Any) -> bool:
        if initial is None:
            initial = []
        if data is None:
            data = []
        if len(initial) != len(data):
            return True
        initial_set = {str(value) for value in self.prepare_value(initial)}
        data_set = {str(value) for value in data}
        return data_set != initial_set

    def value_from_form_data(self, data: Any, files: Any, html_name: str) -> Any:
        return data.getlist(html_name)


def modelfield_to_formfield(
    modelfield: ModelField,
    form_class: type[Field] | None = None,
    choices_form_class: type[Field] | None = None,
    **kwargs: Any,
) -> Field | None:
    """Map a model column-field to an appropriate plain.forms / plain.schema field."""
    # M2M and other non-column-backed fields don't render as form inputs.
    if not isinstance(modelfield, ColumnField):
        return None

    # DB-expression defaults and auto-filled fields produce values automatically.
    auto_filled = modelfield.db_returning or modelfield.auto_fills_on_save

    defaults: dict[str, Any] = {
        "required": modelfield.required and not auto_filled,
    }

    if (
        isinstance(modelfield, DefaultableField)
        and modelfield.has_default()
        and not auto_filled
    ):
        defaults["initial"] = modelfield.get_default()

    if isinstance(modelfield, ChoicesField) and modelfield.choices is not None:
        # Fields with choices get special treatment.
        include_blank = not modelfield.required or not (
            modelfield.has_default() or "initial" in kwargs
        )
        defaults["choices"] = modelfield.get_choices(include_blank=include_blank)
        defaults["coerce"] = modelfield.to_python
        if modelfield.allow_null:
            defaults["empty_value"] = None
        if choices_form_class is not None:
            form_class = choices_form_class
        else:
            form_class = fields.TypedChoiceField
        for k in list(kwargs):
            if k not in (
                "coerce",
                "empty_value",
                "choices",
                "required",
                "initial",
            ):
                del kwargs[k]

    defaults.update(kwargs)

    if form_class is not None:
        return form_class(**defaults)

    from plain import postgres
    from plain.postgres.fields.encrypted import EncryptedJSONField, EncryptedTextField

    if isinstance(modelfield, postgres.PrimaryKeyField):
        return None

    if isinstance(modelfield, postgres.BooleanField):
        form_class = (
            fields.NullBooleanField if modelfield.allow_null else fields.BooleanField
        )
        # HTML checkboxes — 'required' means "must be checked" which is
        # different from the choices case. required=False allows unchecked.
        defaults["required"] = False
        return form_class(**defaults)

    if isinstance(modelfield, postgres.DecimalField):
        return fields.DecimalField(
            max_digits=modelfield.max_digits,
            decimal_places=modelfield.decimal_places,
            **defaults,
        )

    if isinstance(modelfield, EncryptedJSONField):
        return fields.JSONField(
            encoder=modelfield.encoder, decoder=modelfield.decoder, **defaults
        )

    if isinstance(modelfield, EncryptedTextField):
        if modelfield.allow_null:
            defaults["empty_value"] = None
        return fields.TextField(max_length=modelfield.max_length, **defaults)

    if isinstance(modelfield, postgres.TextField):
        if modelfield.allow_null:
            defaults["empty_value"] = None
        return fields.TextField(max_length=modelfield.max_length, **defaults)

    if isinstance(modelfield, postgres.JSONField):
        return fields.JSONField(
            encoder=modelfield.encoder, decoder=modelfield.decoder, **defaults
        )

    if isinstance(modelfield, postgres.ForeignKeyField):
        return ModelChoiceField(
            queryset=modelfield.remote_field.model.query,
            **defaults,
        )

    # If there's a form field of the exact same name, use it.
    if hasattr(fields, modelfield.__class__.__name__):
        form_class = getattr(fields, modelfield.__class__.__name__)
        return form_class(**defaults)

    # Default to TextField if nothing else matches.
    return fields.TextField(**defaults)
