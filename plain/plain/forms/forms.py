"""
Form classes
"""

from __future__ import annotations

import copy
from functools import cached_property
from typing import TYPE_CHECKING, Any

from plain.exceptions import NON_FIELD_ERRORS
from plain.internal import internalcode
from plain.utils.datastructures import MultiValueDict

from .exceptions import ValidationError
from .fields import Field, FileField

if TYPE_CHECKING:
    from plain.http import Request

    from .boundfield import BoundField

__all__ = ("BaseForm", "Form")


@internalcode
class DeclarativeFieldsMetaclass(type):
    """Collect Fields declared on the base classes."""

    def __new__(
        mcs: type[DeclarativeFieldsMetaclass],
        name: str,
        bases: tuple[type, ...],
        attrs: dict[str, Any],
    ) -> type:
        # Collect fields from current class and remove them from attrs.
        attrs["declared_fields"] = {
            key: attrs.pop(key)
            for key, value in list(attrs.items())
            if isinstance(value, Field)
        }

        new_class = super().__new__(mcs, name, bases, attrs)

        # Walk through the MRO.
        declared_fields: dict[str, Field] = {}
        for base in reversed(new_class.__mro__):
            # Collect fields from base class.
            if hasattr(base, "declared_fields"):
                declared_fields.update(getattr(base, "declared_fields"))

            # Field shadowing.
            for attr, value in base.__dict__.items():
                if value is None and attr in declared_fields:
                    declared_fields.pop(attr)

        setattr(new_class, "base_fields", declared_fields)
        setattr(new_class, "declared_fields", declared_fields)

        return new_class


class BaseForm:
    """
    The main implementation of all the Form logic. Note that this class is
    different than Form. See the comments by the Form class for more info. Any
    improvements to the form API should be made to this class, not to the Form
    class.
    """

    # Set by DeclarativeFieldsMetaclass
    base_fields: dict[str, Field]

    prefix: str | None = None

    def __init__(
        self,
        *,
        request: Request,
        auto_id: str | bool = "id_%s",
        prefix: str | None = None,
        initial: dict[str, Any] | None = None,
    ):
        # Forms can handle both JSON and form data
        self.is_json_request = request.headers.get("Content-Type", "").startswith(
            "application/json"
        )
        if self.is_json_request:
            self.data = request.json_data
            self.files = MultiValueDict()
        else:
            self.data = request.form_data
            self.files = request.files

        self.is_bound = bool(self.data or self.files)

        self._auto_id = auto_id
        if prefix is not None:
            self.prefix = prefix
        self.initial = initial or {}
        self._errors: dict[str, list[str]] | None = (
            None  # Stores the errors after clean() has been called.
        )

        # The base_fields class attribute is the *class-wide* definition of
        # fields. Because a particular *instance* of the class might want to
        # alter self.fields, we create self.fields here by copying base_fields.
        # Instances should always modify self.fields; they should not modify
        # self.base_fields.
        self.fields: dict[str, Field] = copy.deepcopy(self.base_fields)
        self._bound_fields_cache: dict[str, BoundField] = {}

    def __repr__(self) -> str:
        if self._errors is None:
            is_valid = "Unknown"
        else:
            is_valid = self.is_bound and not self._errors
        return "<{cls} bound={bound}, valid={valid}, fields=({fields})>".format(
            cls=self.__class__.__name__,
            bound=self.is_bound,
            valid=is_valid,
            fields=";".join(self.fields),
        )

    def _bound_items(self) -> Any:
        """Yield (name, bf) pairs, where bf is a BoundField object."""
        for name in self.fields:
            yield name, self[name]

    def __iter__(self) -> Any:
        """Yield the form's fields as BoundField objects."""
        for name in self.fields:
            yield self[name]

    def __getitem__(self, name: str) -> BoundField:
        """Return a BoundField with the given name."""
        try:
            field = self.fields[name]
        except KeyError:
            raise KeyError(
                "Key '{}' not found in '{}'. Choices are: {}.".format(
                    name,
                    self.__class__.__name__,
                    ", ".join(sorted(self.fields)),
                )
            )
        if name not in self._bound_fields_cache:
            self._bound_fields_cache[name] = field.get_bound_field(self, name)
        return self._bound_fields_cache[name]

    @property
    def errors(self) -> dict[str, list[str]]:
        """Return an error dict for the data provided for the form."""
        if self._errors is None:
            self.full_clean()
        assert self._errors is not None, "full_clean should initialize _errors"
        return self._errors

    def is_valid(self) -> bool:
        """Return True if the form has no errors, or False otherwise."""
        return self.is_bound and not self.errors

    def add_prefix(self, field_name: str) -> str:
        """
        Return the field name with a prefix appended, if this Form has a
        prefix set.

        Subclasses may wish to override.
        """
        return f"{self.prefix}-{field_name}" if self.prefix else field_name

    @property
    def non_field_errors(self) -> list[str]:
        """
        Return a list of errors that aren't associated with a particular
        field -- i.e., from Form.clean(). Return an empty list if there
        are none.
        """
        return self.errors.get(
            NON_FIELD_ERRORS,
            [],
        )

    def add_error(self, field: str | None, error: ValidationError) -> None:
        """
        Update the content of `self._errors`.

        The `field` argument is the name of the field to which the errors
        should be added. If it's None, treat the errors as NON_FIELD_ERRORS.

        The `error` argument can be a single error, a list of errors, or a
        dictionary that maps field names to lists of errors. An "error" can be
        either a simple string or an instance of ValidationError with its
        message attribute set and a "list or dictionary" can be an actual
        `list` or `dict` or an instance of ValidationError with its
        `error_list` or `error_dict` attribute set.

        If `error` is a dictionary, the `field` argument *must* be None and
        errors will be added to the fields that correspond to the keys of the
        dictionary.
        """
        if not isinstance(error, ValidationError):
            raise TypeError(
                "The argument `error` must be an instance of "
                f"`ValidationError`, not `{type(error).__name__}`."
            )

        error_dict: dict[str, Any]
        if hasattr(error, "error_dict"):
            if field is not None:
                raise TypeError(
                    "The argument `field` must be `None` when the `error` "
                    "argument contains errors for multiple fields."
                )
            else:
                error_dict = error.error_dict
        else:
            error_dict = {field or NON_FIELD_ERRORS: error.error_list}

        class ValidationErrors(list):
            def __iter__(self) -> Any:
                for err in super().__iter__():
                    # TODO make sure this works...
                    yield next(iter(err))

        for field_key, error_list in error_dict.items():
            # Accessing self.errors ensures _errors is initialized
            if field_key not in self.errors:
                if field_key != NON_FIELD_ERRORS and field_key not in self.fields:
                    raise ValueError(
                        f"'{self.__class__.__name__}' has no field named '{field_key}'."
                    )
                assert self._errors is not None, "errors property initializes _errors"
                self._errors[field_key] = ValidationErrors()

            assert self._errors is not None, "errors property initializes _errors"
            self._errors[field_key].extend(error_list)

            # The field had an error, so removed it from the final data
            # (we use getattr here so errors can be added to uncleaned forms)
            if field_key in getattr(self, "cleaned_data", {}):
                del self.cleaned_data[field_key]

    def full_clean(self) -> None:
        """
        Clean all of self.data and populate self._errors and self.cleaned_data.
        """
        self._errors = {}
        if not self.is_bound:  # Stop further processing.
            return None
        self.cleaned_data = {}

        self._clean_fields()
        self._clean_form()
        self._post_clean()

    def _field_data_value(self, field: Field, html_name: str) -> Any:
        if hasattr(self, f"parse_{html_name}"):
            # Allow custom parsing from form data/files at the form level
            return getattr(self, f"parse_{html_name}")()

        if self.is_json_request:
            return field.value_from_json_data(self.data, self.files, html_name)
        else:
            return field.value_from_form_data(self.data, self.files, html_name)

    def _clean_fields(self) -> None:
        for name, bf in self._bound_items():
            field = bf.field

            value = self._field_data_value(bf.field, bf.html_name)

            try:
                if isinstance(field, FileField):
                    value = field.clean(value, bf.initial)
                else:
                    value = field.clean(value)
                self.cleaned_data[name] = value
                if hasattr(self, f"clean_{name}"):
                    value = getattr(self, f"clean_{name}")()
                    self.cleaned_data[name] = value
            except ValidationError as e:
                self.add_error(name, e)

    def _clean_form(self) -> None:
        try:
            cleaned_data = self.clean()
        except ValidationError as e:
            self.add_error(None, e)
        else:
            if cleaned_data is not None:
                self.cleaned_data = cleaned_data

    def _post_clean(self) -> None:
        """
        An internal hook for performing additional cleaning after form cleaning
        is complete. Used for model validation in model forms.
        """
        pass

    def clean(self) -> dict[str, Any]:
        """
        Hook for doing any extra form-wide cleaning after Field.clean() has been
        called on every field. Any ValidationError raised by this method will
        not be associated with a particular field; it will have a special-case
        association with the field named '__all__'.
        """
        return self.cleaned_data

    @cached_property
    def changed_data(self) -> list[str]:
        return [name for name, bf in self._bound_items() if bf._has_changed()]

    def get_initial_for_field(self, field: Field, field_name: str) -> Any:
        """
        Return initial data for field on form. Use initial data from the form
        or the field, in that order. Evaluate callable values.
        """
        value = self.initial.get(field_name, field.initial)
        if callable(value):
            value = value()
        return value


class Form(BaseForm, metaclass=DeclarativeFieldsMetaclass):
    "A collection of Fields, plus their associated data."

    # This is a separate class from BaseForm in order to abstract the way
    # self.fields is specified. This class (Form) is the one that does the
    # fancy metaclass stuff purely for the semantic sugar -- it allows one
    # to define a form using declarative syntax.
    # BaseForm itself has no way of designating self.fields.
