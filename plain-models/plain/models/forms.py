"""
Helper functions for creating Form classes from Plain models
and database field objects.
"""
from itertools import chain

from plain.exceptions import (
    NON_FIELD_ERRORS,
    FieldError,
    ImproperlyConfigured,
    ValidationError,
)
from plain.forms import fields
from plain.forms.fields import ChoiceField, Field
from plain.forms.forms import BaseForm, DeclarativeFieldsMetaclass
from plain.models.utils import AltersData

__all__ = (
    "ModelForm",
    "BaseModelForm",
    "model_to_dict",
    "fields_for_model",
    "ModelChoiceField",
    "ModelMultipleChoiceField",
    "ALL_FIELDS",
)

ALL_FIELDS = "__all__"


def construct_instance(form, instance, fields=None):
    """
    Construct and return a model instance from the bound ``form``'s
    ``cleaned_data``, but do not save the returned instance to the database.
    """
    from plain import models

    opts = instance._meta

    cleaned_data = form.cleaned_data
    file_field_list = []
    for f in opts.fields:
        if (
            not f.editable
            or isinstance(f, models.AutoField)
            or f.name not in cleaned_data
        ):
            continue
        if fields is not None and f.name not in fields:
            continue
        # Leave defaults for fields that aren't in POST data, except for
        # checkbox inputs because they don't appear in POST data if not checked.
        if (
            f.has_default()
            and form.add_prefix(f.name) not in form.data
            and form.add_prefix(f.name) not in form.files
            # and form[f.name].field.widget.value_omitted_from_data(
            #     form.data, form.files, form.add_prefix(f.name)
            # )
            and cleaned_data.get(f.name) in form[f.name].field.empty_values
        ):
            continue

        f.save_form_data(instance, cleaned_data[f.name])

    for f in file_field_list:
        f.save_form_data(instance, cleaned_data[f.name])

    return instance


# ModelForms #################################################################


def model_to_dict(instance, fields=None):
    """
    Return a dict containing the data in ``instance`` suitable for passing as
    a Form's ``initial`` keyword argument.

    ``fields`` is an optional list of field names. If provided, return only the
    named.
    """
    opts = instance._meta
    data = {}
    for f in chain(opts.concrete_fields, opts.private_fields, opts.many_to_many):
        if not getattr(f, "editable", False):
            continue
        if fields is not None and f.name not in fields:
            continue
        data[f.name] = f.value_from_object(instance)
    return data


def fields_for_model(
    model,
    fields=None,
    formfield_callback=None,
    error_messages=None,
    field_classes=None,
):
    """
    Return a dictionary containing form fields for the given model.

    ``fields`` is an optional list of field names. If provided, return only the
    named fields.

    ``formfield_callback`` is a callable that takes a model field and returns
    a form field.

    ``error_messages`` is a dictionary of model field names mapped to a
    dictionary of error messages.

    ``field_classes`` is a dictionary of model field names mapped to a form
    field class.
    """
    field_dict = {}
    ignored = []
    opts = model._meta
    # Avoid circular import
    from plain.models.fields import Field as ModelField

    sortable_private_fields = [
        f for f in opts.private_fields if isinstance(f, ModelField)
    ]
    for f in sorted(
        chain(opts.concrete_fields, sortable_private_fields, opts.many_to_many)
    ):
        if not getattr(f, "editable", False):
            if fields is not None and f.name in fields:
                raise FieldError(
                    "'{}' cannot be specified for {} model form as it is a "
                    "non-editable field".format(f.name, model.__name__)
                )
            continue
        if fields is not None and f.name not in fields:
            continue

        kwargs = {}
        if error_messages and f.name in error_messages:
            kwargs["error_messages"] = error_messages[f.name]
        if field_classes and f.name in field_classes:
            kwargs["form_class"] = field_classes[f.name]

        if formfield_callback is None:
            formfield = modelfield_to_formfield(f, **kwargs)
        elif not callable(formfield_callback):
            raise TypeError("formfield_callback must be a function or callable")
        else:
            formfield = formfield_callback(f, **kwargs)

        if formfield:
            field_dict[f.name] = formfield
        else:
            ignored.append(f.name)
    if fields:
        field_dict = {f: field_dict.get(f) for f in fields if f not in ignored}
    return field_dict


class ModelFormOptions:
    def __init__(self, options=None):
        self.model = getattr(options, "model", None)
        self.fields = getattr(options, "fields", None)
        self.error_messages = getattr(options, "error_messages", None)
        self.field_classes = getattr(options, "field_classes", None)
        self.formfield_callback = getattr(options, "formfield_callback", None)


class ModelFormMetaclass(DeclarativeFieldsMetaclass):
    def __new__(mcs, name, bases, attrs):
        new_class = super().__new__(mcs, name, bases, attrs)

        if bases == (BaseModelForm,):
            return new_class

        opts = new_class._meta = ModelFormOptions(getattr(new_class, "Meta", None))

        # We check if a string was passed to `fields`,
        # which is likely to be a mistake where the user typed ('foo') instead
        # of ('foo',)
        for opt in ["fields"]:
            value = getattr(opts, opt)
            if isinstance(value, str) and value != ALL_FIELDS:
                msg = (
                    f"{new_class.__name__}.Meta.{opt} cannot be a string. "
                    f"Did you mean to type: ('{value}',)?"
                )
                raise TypeError(msg)

        if opts.model:
            # If a model is defined, extract form fields from it.
            if opts.fields is None:
                raise ImproperlyConfigured(
                    "Creating a ModelForm without the 'fields' attribute "
                    "is prohibited; form %s "
                    "needs updating." % name
                )

            if opts.fields == ALL_FIELDS:
                # Sentinel for fields_for_model to indicate "get the list of
                # fields from the model"
                opts.fields = None

            fields = fields_for_model(
                opts.model,
                opts.fields,
                opts.formfield_callback,
                opts.error_messages,
                opts.field_classes,
            )

            # make sure opts.fields doesn't specify an invalid field
            none_model_fields = {k for k, v in fields.items() if not v}
            missing_fields = none_model_fields.difference(new_class.declared_fields)
            if missing_fields:
                message = "Unknown field(s) (%s) specified for %s"
                message %= (", ".join(missing_fields), opts.model.__name__)
                raise FieldError(message)
            # Override default model fields with any custom declared ones
            # (plus, include all the other declared fields).
            fields.update(new_class.declared_fields)
        else:
            fields = new_class.declared_fields

        new_class.base_fields = fields

        return new_class


class BaseModelForm(BaseForm, AltersData):
    def __init__(
        self,
        data=None,
        files=None,
        auto_id="id_%s",
        prefix=None,
        initial=None,
        instance=None,
    ):
        opts = self._meta
        if opts.model is None:
            raise ValueError("ModelForm has no model class specified.")
        if instance is None:
            # if we didn't get an instance, instantiate a new one
            self.instance = opts.model()
            object_data = {}
        else:
            self.instance = instance
            object_data = model_to_dict(instance, opts.fields)
        # if initial was provided, it should override the values from instance
        if initial is not None:
            object_data.update(initial)
        # self._validate_unique will be set to True by BaseModelForm.clean().
        # It is False by default so overriding self.clean() and failing to call
        # super will stop validate_unique from being called.
        self._validate_unique = False
        super().__init__(
            data,
            files,
            auto_id,
            prefix,
            object_data,
        )

    def _get_validation_exclusions(self):
        """
        For backwards-compatibility, exclude several types of fields from model
        validation. See tickets #12507, #12521, #12553.
        """
        exclude = set()
        # Build up a list of fields that should be excluded from model field
        # validation and unique checks.
        for f in self.instance._meta.fields:
            field = f.name
            # Exclude fields that aren't on the form. The developer may be
            # adding these values to the model after form validation.
            if field not in self.fields:
                exclude.add(f.name)

            # Don't perform model validation on fields that were defined
            # manually on the form and excluded via the ModelForm's Meta
            # class. See #12901.
            elif self._meta.fields and field not in self._meta.fields:
                exclude.add(f.name)

            # Exclude fields that failed form validation. There's no need for
            # the model fields to validate them as well.
            elif field in self._errors:
                exclude.add(f.name)

            # Exclude empty fields that are not required by the form, if the
            # underlying model field is required. This keeps the model field
            # from raising a required error. Note: don't exclude the field from
            # validation if the model field allows blanks. If it does, the blank
            # value may be included in a unique check, so cannot be excluded
            # from validation.
            else:
                form_field = self.fields[field]
                field_value = self.cleaned_data.get(field)
                if (
                    not f.blank
                    and not form_field.required
                    and field_value in form_field.empty_values
                ):
                    exclude.add(f.name)
        return exclude

    def clean(self):
        self._validate_unique = True
        return self.cleaned_data

    def _update_errors(self, errors):
        # Override any validation error messages defined at the model level
        # with those defined at the form level.
        opts = self._meta

        # Allow the model generated by construct_instance() to raise
        # ValidationError and have them handled in the same way as others.
        if hasattr(errors, "error_dict"):
            error_dict = errors.error_dict
        else:
            error_dict = {NON_FIELD_ERRORS: errors}

        for field, messages in error_dict.items():
            if (
                field == NON_FIELD_ERRORS
                and opts.error_messages
                and NON_FIELD_ERRORS in opts.error_messages
            ):
                error_messages = opts.error_messages[NON_FIELD_ERRORS]
            elif field in self.fields:
                error_messages = self.fields[field].error_messages
            else:
                continue

            for message in messages:
                if (
                    isinstance(message, ValidationError)
                    and message.code in error_messages
                ):
                    message.message = error_messages[message.code]

        self.add_error(None, errors)

    def _post_clean(self):
        opts = self._meta

        exclude = self._get_validation_exclusions()

        # Foreign Keys being used to represent inline relationships
        # are excluded from basic field value validation. This is for two
        # reasons: firstly, the value may not be supplied (#12507; the
        # case of providing new values to the admin); secondly the
        # object being referred to may not yet fully exist (#12749).
        # However, these fields *must* be included in uniqueness checks,
        # so this can't be part of _get_validation_exclusions().
        for name, field in self.fields.items():
            if isinstance(field, InlineForeignKeyField):
                exclude.add(name)

        try:
            self.instance = construct_instance(self, self.instance, opts.fields)
        except ValidationError as e:
            self._update_errors(e)

        try:
            self.instance.full_clean(exclude=exclude, validate_unique=False)
        except ValidationError as e:
            self._update_errors(e)

        # Validate uniqueness if needed.
        if self._validate_unique:
            self.validate_unique()

    def validate_unique(self):
        """
        Call the instance's validate_unique() method and update the form's
        validation errors if any were raised.
        """
        exclude = self._get_validation_exclusions()
        try:
            self.instance.validate_unique(exclude=exclude)
        except ValidationError as e:
            self._update_errors(e)

    def _save_m2m(self):
        """
        Save the many-to-many fields and generic relations for this form.
        """
        cleaned_data = self.cleaned_data
        fields = self._meta.fields
        opts = self.instance._meta
        # Note that for historical reasons we want to include also
        # private_fields here. (GenericRelation was previously a fake
        # m2m field).
        for f in chain(opts.many_to_many, opts.private_fields):
            if not hasattr(f, "save_form_data"):
                continue
            if fields and f.name not in fields:
                continue
            if f.name in cleaned_data:
                f.save_form_data(self.instance, cleaned_data[f.name])

    def save(self, commit=True):
        """
        Save this form's self.instance object if commit=True. Otherwise, add
        a save_m2m() method to the form which can be called after the instance
        is saved manually at a later time. Return the model instance.
        """
        if self.errors:
            raise ValueError(
                "The {} could not be {} because the data didn't validate.".format(
                    self.instance._meta.object_name,
                    "created" if self.instance._state.adding else "changed",
                )
            )
        if commit:
            # If committing, save the instance and the m2m data immediately.
            self.instance.save()
            self._save_m2m()
        else:
            # If not committing, add a method to the form to allow deferred
            # saving of m2m data.
            self.save_m2m = self._save_m2m
        return self.instance

    save.alters_data = True


class ModelForm(BaseModelForm, metaclass=ModelFormMetaclass):
    pass


# Fields #####################################################################


class InlineForeignKeyField(Field):
    """
    A basic integer field that deals with validating the given value to a
    given parent instance in an inline.
    """

    default_error_messages = {
        "invalid_choice": "The inline value did not match the parent instance.",
    }

    def __init__(self, parent_instance, *args, pk_field=False, to_field=None, **kwargs):
        self.parent_instance = parent_instance
        self.pk_field = pk_field
        self.to_field = to_field
        if self.parent_instance is not None:
            if self.to_field:
                kwargs["initial"] = getattr(self.parent_instance, self.to_field)
            else:
                kwargs["initial"] = self.parent_instance.pk
        kwargs["required"] = False
        super().__init__(*args, **kwargs)

    def clean(self, value):
        if value in self.empty_values:
            if self.pk_field:
                return None
            # if there is no value act as we did before.
            return self.parent_instance
        # ensure the we compare the values as equal types.
        if self.to_field:
            orig = getattr(self.parent_instance, self.to_field)
        else:
            orig = self.parent_instance.pk
        if str(value) != str(orig):
            raise ValidationError(
                self.error_messages["invalid_choice"], code="invalid_choice"
            )
        return self.parent_instance

    def has_changed(self, initial, data):
        return False


class ModelChoiceIteratorValue:
    def __init__(self, value, instance):
        self.value = value
        self.instance = instance

    def __str__(self):
        return str(self.value)

    def __hash__(self):
        return hash(self.value)

    def __eq__(self, other):
        if isinstance(other, ModelChoiceIteratorValue):
            other = other.value
        return self.value == other


class ModelChoiceIterator:
    def __init__(self, field):
        self.field = field
        self.queryset = field.queryset

    def __iter__(self):
        if self.field.empty_label is not None:
            yield ("", self.field.empty_label)
        queryset = self.queryset
        # Can't use iterator() when queryset uses prefetch_related()
        if not queryset._prefetch_related_lookups:
            queryset = queryset.iterator()
        for obj in queryset:
            yield self.choice(obj)

    def __len__(self):
        # count() adds a query but uses less memory since the QuerySet results
        # won't be cached. In most cases, the choices will only be iterated on,
        # and __len__() won't be called.
        return self.queryset.count() + (1 if self.field.empty_label is not None else 0)

    def __bool__(self):
        return self.field.empty_label is not None or self.queryset.exists()

    def choice(self, obj):
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
        queryset,
        *,
        empty_label="---------",
        required=True,
        initial=None,
        to_field_name=None,
        blank=False,
        **kwargs,
    ):
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
        self.to_field_name = to_field_name

    def __deepcopy__(self, memo):
        result = super(ChoiceField, self).__deepcopy__(memo)
        # Need to force a new ModelChoiceIterator to be created, bug #11183
        if self.queryset is not None:
            result.queryset = self.queryset.all()
        return result

    def _get_queryset(self):
        return self._queryset

    def _set_queryset(self, queryset):
        self._queryset = None if queryset is None else queryset.all()

    queryset = property(_get_queryset, _set_queryset)

    def _get_choices(self):
        # If self._choices is set, then somebody must have manually set
        # the property self.choices. In this case, just return self._choices.
        if hasattr(self, "_choices"):
            return self._choices

        # Otherwise, execute the QuerySet in self.queryset to determine the
        # choices dynamically. Return a fresh ModelChoiceIterator that has not been
        # consumed. Note that we're instantiating a new ModelChoiceIterator *each*
        # time _get_choices() is called (and, thus, each time self.choices is
        # accessed) so that we can ensure the QuerySet has not been consumed. This
        # construct might look complicated but it allows for lazy evaluation of
        # the queryset.
        return self.iterator(self)

    choices = property(_get_choices, ChoiceField._set_choices)

    def prepare_value(self, value):
        if hasattr(value, "_meta"):
            if self.to_field_name:
                return value.serializable_value(self.to_field_name)
            else:
                return value.pk
        return super().prepare_value(value)

    def to_python(self, value):
        if value in self.empty_values:
            return None
        try:
            key = self.to_field_name or "pk"
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

    def validate(self, value):
        return Field.validate(self, value)

    def has_changed(self, initial, data):
        if self.disabled:
            return False
        initial_value = initial if initial is not None else ""
        data_value = data if data is not None else ""
        return str(self.prepare_value(initial_value)) != str(data_value)


class ModelMultipleChoiceField(ModelChoiceField):
    """A MultipleChoiceField whose choices are a model QuerySet."""

    default_error_messages = {
        "invalid_list": "Enter a list of values.",
        "invalid_choice": "Select a valid choice. %(value)s is not one of the available choices.",
        "invalid_pk_value": "“%(pk)s” is not a valid value.",
    }

    def __init__(self, queryset, **kwargs):
        super().__init__(queryset, empty_label=None, **kwargs)

    def to_python(self, value):
        if not value:
            return []
        return list(self._check_values(value))

    def clean(self, value):
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

    def _check_values(self, value):
        """
        Given a list of possible PK values, return a QuerySet of the
        corresponding objects. Raise a ValidationError if a given value is
        invalid (not a valid PK, not in the queryset, etc.)
        """
        key = self.to_field_name or "pk"
        # deduplicate given values to avoid creating many querysets or
        # requiring the database backend deduplicate efficiently.
        try:
            value = frozenset(value)
        except TypeError:
            # list of lists isn't hashable, for example
            raise ValidationError(
                self.error_messages["invalid_list"],
                code="invalid_list",
            )
        for pk in value:
            try:
                self.queryset.filter(**{key: pk})
            except (ValueError, TypeError):
                raise ValidationError(
                    self.error_messages["invalid_pk_value"],
                    code="invalid_pk_value",
                    params={"pk": pk},
                )
        qs = self.queryset.filter(**{"%s__in" % key: value})
        pks = {str(getattr(o, key)) for o in qs}
        for val in value:
            if str(val) not in pks:
                raise ValidationError(
                    self.error_messages["invalid_choice"],
                    code="invalid_choice",
                    params={"value": val},
                )
        return qs

    def prepare_value(self, value):
        if (
            hasattr(value, "__iter__")
            and not isinstance(value, str)
            and not hasattr(value, "_meta")
        ):
            prepare_value = super().prepare_value
            return [prepare_value(v) for v in value]
        return super().prepare_value(value)

    def has_changed(self, initial, data):
        if self.disabled:
            return False
        if initial is None:
            initial = []
        if data is None:
            data = []
        if len(initial) != len(data):
            return True
        initial_set = {str(value) for value in self.prepare_value(initial)}
        data_set = {str(value) for value in data}
        return data_set != initial_set

    def value_from_form_data(self, data, files, html_name):
        return data.getlist(html_name)


def modelform_defines_fields(form_class):
    return hasattr(form_class, "_meta") and (form_class._meta.fields is not None)


def modelfield_to_formfield(
    modelfield, form_class=None, choices_form_class=None, **kwargs
):
    defaults = {
        "required": not modelfield.blank,
    }

    if modelfield.has_default():
        defaults["initial"] = modelfield.get_default()

    if modelfield.choices is not None:
        # Fields with choices get special treatment.
        include_blank = modelfield.blank or not (
            modelfield.has_default() or "initial" in kwargs
        )
        defaults["choices"] = modelfield.get_choices(include_blank=include_blank)
        defaults["coerce"] = modelfield.to_python
        if modelfield.null:
            defaults["empty_value"] = None
        if choices_form_class is not None:
            form_class = choices_form_class
        else:
            form_class = fields.TypedChoiceField
        # Many of the subclass-specific formfield arguments (min_value,
        # max_value) don't apply for choice fields, so be sure to only pass
        # the values that TypedChoiceField will understand.
        for k in list(kwargs):
            if k not in (
                "coerce",
                "empty_value",
                "choices",
                "required",
                "initial",
                "error_messages",
                "disabled",
            ):
                del kwargs[k]

    defaults.update(kwargs)

    if form_class is not None:
        return form_class(**defaults)

    # Avoid a circular import
    from plain import models

    # Auto fields aren't rendered by default
    if isinstance(modelfield, models.AutoField) or issubclass(
        modelfield.__class__, models.AutoField
    ):
        return None

    if isinstance(modelfield, models.BooleanField):
        form_class = fields.NullBooleanField if modelfield.null else fields.BooleanField
        # In HTML checkboxes, 'required' means "must be checked" which is
        # different from the choices case ("must select some value").
        # required=False allows unchecked checkboxes.
        defaults["required"] = False
        return form_class(**defaults)

    if isinstance(modelfield, models.DecimalField):
        return fields.DecimalField(
            max_digits=modelfield.max_digits,
            decimal_places=modelfield.decimal_places,
            **defaults,
        )

    if issubclass(modelfield.__class__, models.fields.PositiveIntegerRelDbTypeMixin):
        return fields.IntegerField(min_value=0, **defaults)

    if isinstance(modelfield, models.SlugField):
        return fields.SlugField(allow_unicode=modelfield.allow_unicode, **defaults)

    if isinstance(modelfield, models.TextField):
        # Passing max_length to fields.CharField means that the value's length
        # will be validated twice. This is considered acceptable since we want
        # the value in the form field (to pass into widget for example).
        return fields.CharField(max_length=modelfield.max_length, **defaults)

    if isinstance(modelfield, models.CharField):
        # Passing max_length to forms.CharField means that the value's length
        # will be validated twice. This is considered acceptable since we want
        # the value in the form field (to pass into widget for example).
        # TODO: Handle multiple backends with different feature flags.
        from plain.models.db import connection

        if (
            modelfield.null
            and not connection.features.interprets_empty_strings_as_nulls
        ):
            defaults["empty_value"] = None
        return fields.CharField(
            max_length=modelfield.max_length,
            **defaults,
        )

    if isinstance(modelfield, models.JSONField):
        return fields.JSONField(
            encoder=modelfield.encoder, decoder=modelfield.decoder, **defaults
        )

    if isinstance(modelfield, models.ForeignKey):
        return ModelChoiceField(
            queryset=modelfield.remote_field.model._default_manager,
            to_field_name=modelfield.remote_field.field_name,
            blank=modelfield.blank,
            **defaults,
        )

    # TODO related (OneToOne, m2m)

    # If there's a form field of the exact same name, use it
    # (models.URLField -> forms.URLField)
    if hasattr(fields, modelfield.__class__.__name__):
        form_class = getattr(fields, modelfield.__class__.__name__)
        return form_class(**defaults)

    # Default to CharField if we didn't find anything else
    return fields.CharField(**defaults)
