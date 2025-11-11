from __future__ import annotations

import collections.abc
import copy
import datetime
import decimal
import enum
import operator
import uuid
import warnings
from base64 import b64decode, b64encode
from collections.abc import Callable, Sequence
from functools import cached_property, total_ordering
from typing import TYPE_CHECKING, Any, Generic, TypeVar, overload

from plain import exceptions, validators
from plain.models.constants import LOOKUP_SEP
from plain.models.db import db_connection
from plain.models.enums import ChoicesMeta
from plain.models.query_utils import RegisterLookupMixin
from plain.preflight import PreflightResult
from plain.utils import timezone
from plain.utils.datastructures import DictWrapper
from plain.utils.dateparse import (
    parse_date,
    parse_datetime,
    parse_duration,
    parse_time,
)
from plain.utils.duration import duration_microseconds, duration_string
from plain.utils.functional import Promise
from plain.utils.ipv6 import clean_ipv6_address
from plain.utils.itercompat import is_iterable

from ..registry import models_registry

if TYPE_CHECKING:
    from plain.models.backends.base.base import BaseDatabaseWrapper
    from plain.models.fields.reverse_related import ForeignObjectRel
    from plain.models.sql.compiler import SQLCompiler

__all__ = [
    "BLANK_CHOICE_DASH",
    "PrimaryKeyField",
    "BigIntegerField",
    "BinaryField",
    "BooleanField",
    "CharField",
    "DateField",
    "DateTimeField",
    "DecimalField",
    "DurationField",
    "EmailField",
    "Empty",
    "Field",
    "FloatField",
    "GenericIPAddressField",
    "IntegerField",
    "NOT_PROVIDED",
    "PositiveBigIntegerField",
    "PositiveIntegerField",
    "PositiveSmallIntegerField",
    "SmallIntegerField",
    "TextField",
    "TimeField",
    "URLField",
    "UUIDField",
]


class Empty:
    pass


class NOT_PROVIDED:
    pass


# The values to use for "blank" in SelectFields. Will be appended to the start
# of most "choices" lists.
BLANK_CHOICE_DASH = [("", "---------")]


def _load_field(package_label: str, model_name: str, field_name: str) -> Field:
    return models_registry.get_model(package_label, model_name)._model_meta.get_field(
        field_name
    )


# A guide to Field parameters:
#
#   * name:      The name of the field specified in the model.
#   * attname:   The attribute to use on the model object. This is the same as
#                "name", except in the case of ForeignKeys, where "_id" is
#                appended.
#   * db_column: The db_column specified in the model (or None).
#   * column:    The database column for this field. This is the same as
#                "attname", except if db_column is specified.
#
# Code that introspects values, or does other dynamic things, should use
# attname.


def _empty(of_cls: type) -> Empty:
    new = Empty()
    new.__class__ = of_cls
    return new


def return_None() -> None:
    return None


# TypeVar for Field's generic type parameter
T = TypeVar("T")


@total_ordering
class Field(RegisterLookupMixin, Generic[T]):
    """Base class for all field types"""

    # Designates whether empty strings fundamentally are allowed at the
    # database level.
    empty_strings_allowed = True
    empty_values = list(validators.EMPTY_VALUES)

    # These track each time a Field instance is created. Used to retain order.
    # The auto_creation_counter is used for fields that Plain implicitly
    # creates, creation_counter is used for all user-specified fields.
    creation_counter = 0
    auto_creation_counter = -1
    default_validators = []  # Default set of validators
    default_error_messages = {
        "invalid_choice": "Value %(value)r is not a valid choice.",
        "allow_null": "This field cannot be null.",
        "required": "This field is be required.",
        "unique": "A %(model_name)s with this %(field_label)s already exists.",
    }

    # Attributes that don't affect a column definition.
    # These attributes are ignored when altering the field.
    non_db_attrs = (
        "required",
        "choices",
        "db_column",
        "error_messages",
        "limit_choices_to",
        # Database-level options are not supported, see #21961.
        "on_delete",
        "related_name",
        "related_query_name",
        "validators",
    )

    # Field flags
    hidden = False

    many_to_many = None
    many_to_one = None
    one_to_many = None
    related_model = None

    # Generic field type description, usually overridden by subclasses
    def _description(self) -> str:
        return f"Field of type: {self.__class__.__name__}"

    description = property(_description)

    def __init__(
        self,
        *,
        max_length: int | None = None,
        required: bool = True,
        allow_null: bool = False,
        rel: ForeignObjectRel | None = None,
        default: Any = NOT_PROVIDED,
        choices: Any = None,
        db_column: str | None = None,
        validators: Sequence[Callable[..., Any]] = (),
        error_messages: dict[str, str] | None = None,
        db_comment: str | None = None,
    ):
        self.name = None  # Set by set_attributes_from_name
        self.max_length = max_length
        self.required, self.allow_null = required, allow_null
        self.remote_field = rel
        self.is_relation = self.remote_field is not None
        self.default = default
        if isinstance(choices, ChoicesMeta):
            choices = choices.choices
        elif isinstance(choices, enum.EnumMeta):
            choices = [(member.value, member.name) for member in choices]
        if isinstance(choices, collections.abc.Iterator):
            choices = list(choices)
        self.choices = choices
        self.db_column = db_column
        self.db_comment = db_comment

        self.primary_key = False
        self.auto_created = False

        # Adjust the appropriate creation counter, and save our local copy.
        self.creation_counter = Field.creation_counter
        Field.creation_counter += 1

        self._validators = list(validators)  # Store for deconstruction later

        self._error_messages = error_messages  # Store for deconstruction later

    def __str__(self) -> str:
        """
        Return "package_label.model_label.field_name" for fields attached to
        models.
        """
        if not hasattr(self, "model"):
            return super().__str__()
        model = self.model
        return f"{model.model_options.label}.{self.name}"

    def __repr__(self) -> str:
        """Display the module, class, and name of the field."""
        path = f"{self.__class__.__module__}.{self.__class__.__qualname__}"
        name = getattr(self, "name", None)
        if name is not None:
            return f"<{path}: {name}>"
        return f"<{path}>"

    def preflight(self, **kwargs: Any) -> list[PreflightResult]:
        return [
            *self._check_field_name(),
            *self._check_choices(),
            *self._check_db_comment(),
            *self._check_null_allowed_for_primary_keys(),
            *self._check_backend_specific_checks(),
            *self._check_validators(),
        ]

    def _check_field_name(self) -> list[PreflightResult]:
        """
        Check if field name is valid, i.e. 1) does not end with an
        underscore, 2) does not contain "__" and 3) is not "id".
        """
        if self.name.endswith("_"):
            return [
                PreflightResult(
                    fix="Field names must not end with an underscore.",
                    obj=self,
                    id="fields.name_ends_with_underscore",
                )
            ]
        elif LOOKUP_SEP in self.name:
            return [
                PreflightResult(
                    fix=f'Field names must not contain "{LOOKUP_SEP}".',
                    obj=self,
                    id="fields.name_contains_lookup_separator",
                )
            ]
        elif self.name == "id":
            return [
                PreflightResult(
                    fix="'id' is a reserved word that cannot be used as a field name.",
                    obj=self,
                    id="fields.reserved_field_name_id",
                )
            ]
        else:
            return []

    @classmethod
    def _choices_is_value(cls, value: Any) -> bool:
        return isinstance(value, str | Promise) or not is_iterable(value)

    def _check_choices(self) -> list[PreflightResult]:
        if not self.choices:
            return []

        if not is_iterable(self.choices) or isinstance(self.choices, str):
            return [
                PreflightResult(
                    fix="'choices' must be an iterable (e.g., a list or tuple).",
                    obj=self,
                    id="fields.choices_not_iterable",
                )
            ]

        choice_max_length = 0
        # Expect [group_name, [value, display]]
        for choices_group in self.choices:
            try:
                group_name, group_choices = choices_group
            except (TypeError, ValueError):
                # Containing non-pairs
                break
            try:
                if not all(
                    self._choices_is_value(value) and self._choices_is_value(human_name)
                    for value, human_name in group_choices
                ):
                    break
                if self.max_length is not None and group_choices:
                    choice_max_length = max(
                        [
                            choice_max_length,
                            *(
                                len(value)
                                for value, _ in group_choices
                                if isinstance(value, str)
                            ),
                        ]
                    )
            except (TypeError, ValueError):
                # No groups, choices in the form [value, display]
                value, human_name = group_name, group_choices
                if not self._choices_is_value(value) or not self._choices_is_value(
                    human_name
                ):
                    break
                if self.max_length is not None and isinstance(value, str):
                    choice_max_length = max(choice_max_length, len(value))

            # Special case: choices=['ab']
            if isinstance(choices_group, str):
                break
        else:
            if self.max_length is not None and choice_max_length > self.max_length:
                return [
                    PreflightResult(
                        fix="'max_length' is too small to fit the longest value "  # noqa: UP031
                        "in 'choices' (%d characters)." % choice_max_length,
                        obj=self,
                        id="fields.max_length_too_small_for_choices",
                    ),
                ]
            return []

        return [
            PreflightResult(
                fix="'choices' must be an iterable containing "
                "(actual value, human readable name) tuples.",
                obj=self,
                id="fields.choices_invalid_format",
            )
        ]

    def _check_db_comment(self) -> list[PreflightResult]:
        if not self.db_comment:
            return []
        errors = []
        if not (
            db_connection.features.supports_comments
            or "supports_comments" in self.model.model_options.required_db_features
        ):
            errors.append(
                PreflightResult(
                    fix=f"{db_connection.display_name} does not support comments on "
                    f"columns (db_comment).",
                    obj=self,
                    id="fields.db_comment_unsupported",
                    warning=True,
                )
            )
        return errors

    def _check_null_allowed_for_primary_keys(self) -> list[PreflightResult]:
        if self.primary_key and self.allow_null:
            # We cannot reliably check this for backends like Oracle which
            # consider NULL and '' to be equal (and thus set up
            # character-based fields a little differently).
            return [
                PreflightResult(
                    fix="Primary keys must not have allow_null=True. "
                    "Set allow_null=False on the field, or "
                    "remove primary_key=True argument.",
                    obj=self,
                    id="fields.primary_key_allows_null",
                )
            ]
        else:
            return []

    def _check_backend_specific_checks(self) -> list[PreflightResult]:
        errors = []
        errors.extend(db_connection.validation.check_field(self))
        return errors

    def _check_validators(self) -> list[PreflightResult]:
        errors = []
        for i, validator in enumerate(self.validators):
            if not callable(validator):
                errors.append(
                    PreflightResult(
                        fix=(
                            "All 'validators' must be callable. "
                            f"validators[{i}] ({repr(validator)}) isn't a function or "
                            "instance of a validator class."
                        ),
                        obj=self,
                        id="fields.invalid_validator",
                    )
                )
        return errors

    def get_col(self, alias: str, output_field: Field | None = None) -> Any:
        if alias == self.model.model_options.db_table and (
            output_field is None or output_field == self
        ):
            return self.cached_col
        from plain.models.expressions import Col

        return Col(alias, self, output_field)

    @cached_property
    def cached_col(self) -> Any:
        from plain.models.expressions import Col

        return Col(self.model.model_options.db_table, self)

    def select_format(
        self, compiler: SQLCompiler, sql: str, params: Any
    ) -> tuple[str, Any]:
        """
        Custom format for select clauses. For example, GIS columns need to be
        selected as AsText(table.col) on MySQL as the table.col data can't be
        used by Plain.
        """
        return sql, params

    def deconstruct(self) -> tuple[str, str, list[Any], dict[str, Any]]:
        """
        Return enough information to recreate the field as a 4-tuple:

         * The name of the field on the model, if contribute_to_class() has
           been run.
         * The import path of the field, including the class, e.g.
           plain.models.IntegerField. This should be the most portable
           version, so less specific may be better.
         * A list of positional arguments.
         * A dict of keyword arguments.

        Note that the positional or keyword arguments must contain values of
        the following types (including inner values of collection types):

         * None, bool, str, int, float, complex, set, frozenset, list, tuple,
           dict
         * UUID
         * datetime.datetime (naive), datetime.date
         * top-level classes, top-level functions - will be referenced by their
           full import path
         * Storage instances - these have their own deconstruct() method

        This is because the values here must be serialized into a text format
        (possibly new Python code, possibly JSON) and these are the only types
        with encoding handlers defined.

        There's no need to return the exact way the field was instantiated this
        time, just ensure that the resulting field is the same - prefer keyword
        arguments over positional ones, and omit parameters with their default
        values.
        """
        # Short-form way of fetching all the default parameters
        keywords = {}
        possibles = {
            "max_length": None,
            "required": True,
            "allow_null": False,
            "default": NOT_PROVIDED,
            "choices": None,
            "db_column": None,
            "db_comment": None,
            "validators": [],
            "error_messages": None,
        }
        attr_overrides = {
            "error_messages": "_error_messages",
            "validators": "_validators",
        }
        equals_comparison = {"choices", "validators"}
        for name, default in possibles.items():
            value = getattr(self, attr_overrides.get(name, name))
            # Unroll anything iterable for choices into a concrete list
            if name == "choices" and isinstance(value, collections.abc.Iterable):
                value = list(value)
            # Do correct kind of comparison
            if name in equals_comparison:
                if value != default:
                    keywords[name] = value
            else:
                if value is not default:
                    keywords[name] = value
        # Work out path - we shorten it for known Plain core fields
        path = f"{self.__class__.__module__}.{self.__class__.__qualname__}"
        if path.startswith("plain.models.fields.related"):
            path = path.replace("plain.models.fields.related", "plain.models")
        elif path.startswith("plain.models.fields.json"):
            path = path.replace("plain.models.fields.json", "plain.models")
        elif path.startswith("plain.models.fields.proxy"):
            path = path.replace("plain.models.fields.proxy", "plain.models")
        elif path.startswith("plain.models.fields"):
            path = path.replace("plain.models.fields", "plain.models")
        # Return basic info - other fields should override this.
        return (self.name, path, [], keywords)

    def clone(self) -> Field:
        """
        Uses deconstruct() to clone a new copy of this Field.
        Will not preserve any class attachments/attribute names.
        """
        name, path, args, kwargs = self.deconstruct()
        return self.__class__(*args, **kwargs)

    def __eq__(self, other: object) -> bool:
        # Needed for @total_ordering
        if isinstance(other, Field):
            return self.creation_counter == other.creation_counter and getattr(
                self, "model", None
            ) == getattr(other, "model", None)
        return NotImplemented

    def __lt__(self, other: object) -> bool:
        # This is needed because bisect does not take a comparison function.
        # Order by creation_counter first for backward compatibility.
        if not isinstance(other, Field):
            return NotImplemented

        # Type narrowing: other is now known to be a Field
        other_field: Field[Any] = other

        if (
            self.creation_counter != other_field.creation_counter
            or not hasattr(self, "model")
            and not hasattr(other_field, "model")
        ):
            return self.creation_counter < other_field.creation_counter
        elif hasattr(self, "model") != hasattr(other_field, "model"):
            return not hasattr(self, "model")  # Order no-model fields first
        else:
            # creation_counter's are equal, compare only models.
            # Use getattr with defaults to satisfy type checker
            self_pkg = getattr(getattr(self, "model", None), "model_options", None)
            other_pkg = getattr(
                getattr(other_field, "model", None), "model_options", None
            )
            if self_pkg is not None and other_pkg is not None:
                return (
                    self_pkg.package_label,
                    self_pkg.model_name,
                ) < (
                    other_pkg.package_label,
                    other_pkg.model_name,
                )
            # Fallback if model_options not available
            return self.creation_counter < other_field.creation_counter

    def __hash__(self) -> int:
        return hash(self.creation_counter)

    def __deepcopy__(self, memodict: dict[int, Any]) -> Field:
        # We don't have to deepcopy very much here, since most things are not
        # intended to be altered after initial creation.
        obj = copy.copy(self)
        if self.remote_field:
            obj.remote_field = copy.copy(self.remote_field)
            if hasattr(self.remote_field, "field") and self.remote_field.field is self:
                obj.remote_field.field = obj
        memodict[id(self)] = obj
        return obj

    def __copy__(self) -> Field:
        # We need to avoid hitting __reduce__, so define this
        # slightly weird copy construct.
        obj = Empty()
        obj.__class__ = self.__class__
        obj.__dict__ = self.__dict__.copy()
        return obj  # type: ignore[return-value]

    def __reduce__(
        self,
    ) -> (
        tuple[Callable[..., Any], tuple[Any, ...], dict[str, Any]]
        | tuple[Callable[..., Field], tuple[str, str, str]]
    ):
        """
        Pickling should return the model._model_meta.fields instance of the field,
        not a new copy of that field. So, use the app registry to load the
        model and then the field back.
        """
        if not hasattr(self, "model"):
            # Fields are sometimes used without attaching them to models (for
            # example in aggregation). In this case give back a plain field
            # instance. The code below will create a new empty instance of
            # class self.__class__, then update its dict with self.__dict__
            # values - so, this is very close to normal pickle.
            state = self.__dict__.copy()
            # The _get_default cached_property can't be pickled due to lambda
            # usage.
            state.pop("_get_default", None)
            return _empty, (self.__class__,), state
        return _load_field, (
            self.model.model_options.package_label,
            self.model.model_options.object_name,
            self.name,
        )

    def get_id_value_on_save(self, instance: Any) -> Any:
        """
        Hook to generate new primary key values on save. This method is called when
        saving instances with no primary key value set. If this method returns
        something else than None, then the returned value is used when saving
        the new instance.
        """
        if self.default:
            return self.get_default()
        return None

    def to_python(self, value: Any) -> Any:
        """
        Convert the input value into the expected Python data type, raising
        plain.exceptions.ValidationError if the data can't be converted.
        Return the converted value. Subclasses should override this.
        """
        return value

    @cached_property
    def error_messages(self) -> dict[str, str]:
        messages = {}
        for c in reversed(self.__class__.__mro__):
            messages.update(getattr(c, "default_error_messages", {}))
        messages.update(self._error_messages or {})
        return messages

    @cached_property
    def validators(self) -> list[Callable[..., Any]]:
        """
        Some validators can't be created at field initialization time.
        This method provides a way to delay their creation until required.
        """
        return [*self.default_validators, *self._validators]

    def run_validators(self, value: Any) -> None:
        if value in self.empty_values:
            return

        errors = []
        for v in self.validators:
            try:
                v(value)
            except exceptions.ValidationError as e:
                if hasattr(e, "code") and e.code in self.error_messages:
                    e.message = self.error_messages[e.code]
                errors.extend(e.error_list)

        if errors:
            raise exceptions.ValidationError(errors)

    def validate(self, value: Any, model_instance: Any) -> None:
        """
        Validate value and raise ValidationError if necessary. Subclasses
        should override this to provide validation logic.
        """

        if self.choices is not None and value not in self.empty_values:
            for option_key, option_value in self.choices:
                if isinstance(option_value, list | tuple):
                    # This is an optgroup, so look inside the group for
                    # options.
                    for optgroup_key, optgroup_value in option_value:
                        if value == optgroup_key:
                            return
                elif value == option_key:
                    return
            raise exceptions.ValidationError(
                self.error_messages["invalid_choice"],
                code="invalid_choice",
                params={"value": value},
            )

        if value is None and not self.allow_null:
            raise exceptions.ValidationError(
                self.error_messages["allow_null"], code="allow_null"
            )

        if self.required and value in self.empty_values:
            raise exceptions.ValidationError(
                self.error_messages["required"], code="required"
            )

    def clean(self, value: Any, model_instance: Any) -> Any:
        """
        Convert the value's type and run validation. Validation errors
        from to_python() and validate() are propagated. Return the correct
        value if no error is raised.
        """
        value = self.to_python(value)
        self.validate(value, model_instance)
        self.run_validators(value)
        return value

    def db_type_parameters(self, connection: BaseDatabaseWrapper) -> DictWrapper:
        return DictWrapper(self.__dict__, connection.ops.quote_name, "qn_")

    def db_check(self, connection: BaseDatabaseWrapper) -> str | None:
        """
        Return the database column check constraint for this field, for the
        provided connection. Works the same way as db_type() for the case that
        get_internal_type() does not map to a preexisting model field.
        """
        data = self.db_type_parameters(connection)
        try:
            return (
                connection.data_type_check_constraints[self.get_internal_type()] % data
            )
        except KeyError:
            return None

    def db_type(self, connection: BaseDatabaseWrapper) -> str | None:
        """
        Return the database column data type for this field, for the provided
        connection.
        """
        # The default implementation of this method looks at the
        # backend-specific data_types dictionary, looking up the field by its
        # "internal type".
        #
        # A Field class can implement the get_internal_type() method to specify
        # which *preexisting* Plain Field class it's most similar to -- i.e.,
        # a custom field might be represented by a TEXT column type, which is
        # the same as the TextField Plain field type, which means the custom
        # field's get_internal_type() returns 'TextField'.
        #
        # But the limitation of the get_internal_type() / data_types approach
        # is that it cannot handle database column types that aren't already
        # mapped to one of the built-in Plain field types. In this case, you
        # can implement db_type() instead of get_internal_type() to specify
        # exactly which wacky database column type you want to use.
        data = self.db_type_parameters(connection)
        try:
            column_type = connection.data_types[self.get_internal_type()]
        except KeyError:
            return None
        else:
            # column_type is either a single-parameter function or a string.
            if callable(column_type):
                return column_type(data)
            return column_type % data

    def rel_db_type(self, connection: BaseDatabaseWrapper) -> str | None:
        """
        Return the data type that a related field pointing to this field should
        use. For example, this method is called by ForeignKey to determine its data type.
        """
        return self.db_type(connection)

    def cast_db_type(self, connection: BaseDatabaseWrapper) -> str | None:
        """Return the data type to use in the Cast() function."""
        db_type = connection.ops.cast_data_types.get(self.get_internal_type())
        if db_type:
            return db_type % self.db_type_parameters(connection)
        return self.db_type(connection)

    def db_parameters(self, connection: BaseDatabaseWrapper) -> dict[str, Any]:
        """
        Extension of db_type(), providing a range of different return values
        (type, checks). This will look at db_type(), allowing custom model
        fields to override it.
        """
        type_string = self.db_type(connection)
        check_string = self.db_check(connection)
        return {
            "type": type_string,
            "check": check_string,
        }

    def db_type_suffix(self, connection: BaseDatabaseWrapper) -> str | None:
        return connection.data_types_suffix.get(self.get_internal_type())

    def get_db_converters(
        self, connection: BaseDatabaseWrapper
    ) -> list[Callable[..., Any]]:
        if hasattr(self, "from_db_value"):
            return [self.from_db_value]
        return []

    @property
    def db_returning(self) -> bool:
        """
        Private API intended only to be used by Plain itself. Currently only
        the PostgreSQL backend supports returning multiple fields on a model.
        """
        return False

    def set_attributes_from_name(self, name: str) -> None:
        self.name = self.name or name
        self.attname, self.column = self.get_attname_column()
        self.concrete = self.column is not None

    def contribute_to_class(self, cls: Any, name: str) -> None:
        """
        Register the field with the model class it belongs to.

        Field now acts as its own descriptor - it stays on the class and handles
        __get__/__set__/__delete__ directly.
        """
        self.set_attributes_from_name(name)
        self.model = cls
        cls._model_meta.add_field(self)

        # Field is now a descriptor itself - ensure it's set on the class
        # This is important for inherited fields that get deepcopied in Meta.__get__
        if self.column:
            setattr(cls, self.attname, self)

    # Descriptor protocol implementation
    @overload
    def __get__(self, instance: None, owner: type) -> Field[T]: ...

    @overload
    def __get__(self, instance: Any, owner: type) -> T: ...

    def __get__(self, instance: Any | None, owner: type) -> Field[T] | T:
        """
        Descriptor __get__ for attribute access.

        Class access (User.email) returns the Field descriptor itself.
        Instance access (user.email) returns the field value from instance.__dict__,
        with lazy loading support if the value is not yet loaded.
        """
        # Class access - return the Field descriptor
        if instance is None:
            return self

        # If field hasn't been contributed to a class yet (e.g., used standalone
        # as an output_field in aggregates), just return self
        if not hasattr(self, "attname"):
            return self

        # Instance access - get value from instance dict
        data = instance.__dict__
        field_name = self.attname

        # If value not in dict, lazy load from database
        if field_name not in data:
            # Deferred field - load it from the database
            instance.refresh_from_db(fields=[field_name])

        return data.get(field_name)

    def __set__(self, instance: Any, value: Any) -> None:
        """
        Descriptor __set__ for attribute assignment.

        Validates and converts the value using to_python(), then stores it
        in instance.__dict__[attname].
        """
        # Safety check: ensure field has been properly initialized
        if not hasattr(self, "attname"):
            raise AttributeError(
                f"Field {self.__class__.__name__} has not been initialized properly. "
                f"The field's contribute_to_class() has not been called yet. "
                f"This usually means the field is being used before it was added to a model class."
            )

        # Convert/validate the value
        if value is not None:
            value = self.to_python(value)

        # Store in instance dict
        instance.__dict__[self.attname] = value

    def __delete__(self, instance: Any) -> None:
        """
        Descriptor __delete__ for attribute deletion.

        Removes the value from instance.__dict__.
        """
        try:
            del instance.__dict__[self.attname]
        except KeyError:
            raise AttributeError(
                f"{instance.__class__.__name__!r} object has no attribute {self.attname!r}"
            )

    def get_attname(self) -> str:
        return self.name

    def get_attname_column(self) -> tuple[str, str]:
        attname = self.get_attname()
        column = self.db_column or attname
        return attname, column

    def get_internal_type(self) -> str:
        return self.__class__.__name__

    def pre_save(self, model_instance: Any, add: bool) -> Any:
        """Return field's value just before saving."""
        return getattr(model_instance, self.attname)

    def get_prep_value(self, value: Any) -> Any:
        """Perform preliminary non-db specific value checks and conversions."""
        if isinstance(value, Promise):
            value = value._proxy____cast()
        return value

    def get_db_prep_value(
        self, value: Any, connection: BaseDatabaseWrapper, prepared: bool = False
    ) -> Any:
        """
        Return field's value prepared for interacting with the database backend.

        Used by the default implementations of get_db_prep_save().
        """
        if not prepared:
            value = self.get_prep_value(value)
        return value

    def get_db_prep_save(self, value: Any, connection: BaseDatabaseWrapper) -> Any:
        """Return field's value prepared for saving into a database."""
        if hasattr(value, "as_sql"):
            return value
        return self.get_db_prep_value(value, connection=connection, prepared=False)

    def has_default(self) -> bool:
        """Return a boolean of whether this field has a default value."""
        return self.default is not NOT_PROVIDED

    def get_default(self) -> Any:
        """Return the default value for this field."""
        return self._get_default()

    @cached_property
    def _get_default(self) -> Callable[[], Any]:
        if self.has_default():
            if callable(self.default):
                return self.default
            return lambda: self.default

        if not self.empty_strings_allowed or self.allow_null:
            return return_None
        return str  # return empty string

    def get_choices(
        self,
        include_blank: bool = True,
        blank_choice: list[tuple[str, str]] = BLANK_CHOICE_DASH,
        limit_choices_to: Any = None,
        ordering: tuple[str, ...] = (),
    ) -> list[tuple[Any, str]]:
        """
        Return choices with a default blank choices included, for use
        as <select> choices for this field.
        """
        if self.choices is not None:
            choices = list(self.choices)
            if include_blank:
                blank_defined = any(
                    choice in ("", None) for choice, _ in self.flatchoices
                )
                if not blank_defined:
                    choices = blank_choice + choices
            return choices
        rel_model = self.remote_field.model
        limit_choices_to = limit_choices_to or self.get_limit_choices_to()
        choice_func = operator.attrgetter(
            self.remote_field.get_related_field().attname
            if hasattr(self.remote_field, "get_related_field")
            else "id"
        )
        qs = rel_model.query.complex_filter(limit_choices_to)
        if ordering:
            qs = qs.order_by(*ordering)
        return (blank_choice if include_blank else []) + [
            (choice_func(x), str(x)) for x in qs
        ]

    def value_to_string(self, obj: Any) -> str:
        """
        Return a string value of this field from the passed obj.
        This is used by the serialization framework.
        """
        return str(self.value_from_object(obj))

    def _get_flatchoices(self) -> list[tuple[Any, Any]]:
        """Flattened version of choices tuple."""
        if self.choices is None:
            return []
        flat = []
        for choice, value in self.choices:
            if isinstance(value, list | tuple):
                flat.extend(value)
            else:
                flat.append((choice, value))
        return flat

    flatchoices = property(_get_flatchoices)

    def save_form_data(self, instance: Any, data: Any) -> None:
        setattr(instance, self.name, data)

    def value_from_object(self, obj: Any) -> Any:
        """Return the value of this field in the given model instance."""
        return getattr(obj, self.attname)


class BooleanField(Field[bool]):
    empty_strings_allowed = False
    default_error_messages = {
        "invalid": '"%(value)s" value must be either True or False.',
        "invalid_nullable": '"%(value)s" value must be either True, False, or None.',
    }
    description = "Boolean (Either True or False)"

    def get_internal_type(self) -> str:
        return "BooleanField"

    def to_python(self, value: Any) -> Any:
        if self.allow_null and value in self.empty_values:
            return None
        if value in (True, False):
            # 1/0 are equal to True/False. bool() converts former to latter.
            return bool(value)
        if value in ("t", "True", "1"):
            return True
        if value in ("f", "False", "0"):
            return False
        raise exceptions.ValidationError(
            self.error_messages["invalid_nullable" if self.allow_null else "invalid"],
            code="invalid",
            params={"value": value},
        )

    def get_prep_value(self, value: Any) -> Any:
        value = super().get_prep_value(value)
        if value is None:
            return None
        return self.to_python(value)


class CharField(Field[str]):
    def __init__(self, *, db_collation: str | None = None, **kwargs: Any):
        super().__init__(**kwargs)
        self.db_collation = db_collation
        if self.max_length is not None:
            self.validators.append(validators.MaxLengthValidator(self.max_length))

    @property
    def description(self) -> str:
        if self.max_length is not None:
            return "String (up to %(max_length)s)"
        else:
            return "String (unlimited)"

    def preflight(self, **kwargs: Any) -> list[PreflightResult]:
        return [
            *super().preflight(**kwargs),
            *self._check_db_collation(),
            *self._check_max_length_attribute(),
        ]

    def _check_max_length_attribute(self, **kwargs: Any) -> list[PreflightResult]:
        if self.max_length is None:
            if (
                db_connection.features.supports_unlimited_charfield
                or "supports_unlimited_charfield"
                in self.model.model_options.required_db_features
            ):
                return []
            return [
                PreflightResult(
                    fix="CharFields must define a 'max_length' attribute.",
                    obj=self,
                    id="fields.charfield_missing_max_length",
                )
            ]
        elif (
            not isinstance(self.max_length, int)
            or isinstance(self.max_length, bool)
            or self.max_length <= 0
        ):
            return [
                PreflightResult(
                    fix="'max_length' must be a positive integer.",
                    obj=self,
                    id="fields.charfield_invalid_max_length",
                )
            ]
        else:
            return []

    def _check_db_collation(self) -> list[PreflightResult]:
        errors = []
        if not (
            self.db_collation is None
            or "supports_collation_on_charfield"
            in self.model.model_options.required_db_features
            or db_connection.features.supports_collation_on_charfield
        ):
            errors.append(
                PreflightResult(
                    fix=f"{db_connection.display_name} does not support a database collation on "
                    "CharFields.",
                    obj=self,
                    id="fields.db_collation_unsupported",
                ),
            )
        return errors

    def cast_db_type(self, connection: BaseDatabaseWrapper) -> str | None:
        if self.max_length is None:
            return connection.ops.cast_char_field_without_max_length
        return super().cast_db_type(connection)

    def db_parameters(self, connection: BaseDatabaseWrapper) -> dict[str, Any]:
        db_params = super().db_parameters(connection)
        db_params["collation"] = self.db_collation
        return db_params

    def get_internal_type(self) -> str:
        return "CharField"

    def to_python(self, value: Any) -> Any:
        if isinstance(value, str) or value is None:
            return value
        return str(value)

    def get_prep_value(self, value: Any) -> Any:
        value = super().get_prep_value(value)
        return self.to_python(value)

    def deconstruct(self) -> tuple[str, str, list[Any], dict[str, Any]]:
        name, path, args, kwargs = super().deconstruct()
        if self.db_collation:
            kwargs["db_collation"] = self.db_collation
        return name, path, args, kwargs


def _to_naive(value: datetime.datetime) -> datetime.datetime:
    if timezone.is_aware(value):
        value = timezone.make_naive(value, datetime.UTC)
    return value


def _get_naive_now() -> datetime.datetime:
    return _to_naive(timezone.now())


class DateTimeCheckMixin:
    def preflight(self, **kwargs: Any) -> list[PreflightResult]:  # type: ignore[misc]
        return [
            *super().preflight(**kwargs),  # type: ignore[misc]
            *self._check_mutually_exclusive_options(),
            *self._check_fix_default_value(),
        ]

    def _check_mutually_exclusive_options(self) -> list[PreflightResult]:
        # auto_now, auto_now_add, and default are mutually exclusive
        # options. The use of more than one of these options together
        # will trigger an Error
        mutually_exclusive_options = [
            self.auto_now_add,  # type: ignore[attr-defined]
            self.auto_now,  # type: ignore[attr-defined]
            self.has_default(),  # type: ignore[attr-defined]
        ]
        enabled_options = [
            option not in (None, False) for option in mutually_exclusive_options
        ].count(True)
        if enabled_options > 1:
            return [
                PreflightResult(
                    fix="The options auto_now, auto_now_add, and default "
                    "are mutually exclusive. Only one of these options "
                    "may be present.",
                    obj=self,
                    id="fields.datetime_auto_options_mutually_exclusive",
                )
            ]
        else:
            return []

    def _check_fix_default_value(self) -> list[PreflightResult]:
        return []

    # Concrete subclasses use this in their implementations of
    # _check_fix_default_value().
    def _check_if_value_fixed(
        self,
        value: datetime.date | datetime.datetime,
        now: datetime.datetime | None = None,
    ) -> list[PreflightResult]:
        """
        Check if the given value appears to have been provided as a "fixed"
        time value, and include a warning in the returned list if it does. The
        value argument must be a date object or aware/naive datetime object. If
        now is provided, it must be a naive datetime object.
        """
        if now is None:
            now = _get_naive_now()
        offset = datetime.timedelta(seconds=10)
        lower = now - offset
        upper = now + offset
        if isinstance(value, datetime.datetime):
            value = _to_naive(value)
        else:
            assert isinstance(value, datetime.date)
            lower = lower.date()
            upper = upper.date()
        if lower <= value <= upper:
            return [
                PreflightResult(
                    fix="Fixed default value provided. "
                    "It seems you set a fixed date / time / datetime "
                    "value as default for this field. This may not be "
                    "what you want. If you want to have the current date "
                    "as default, use `plain.utils.timezone.now`",
                    obj=self,
                    id="fields.datetime_naive_default_value",
                    warning=True,
                )
            ]
        return []


class DateField(DateTimeCheckMixin, Field[datetime.date]):
    empty_strings_allowed = False
    default_error_messages = {
        "invalid": '"%(value)s" value has an invalid date format. It must be in YYYY-MM-DD format.',
        "invalid_date": '"%(value)s" value has the correct format (YYYY-MM-DD) but it is an invalid date.',
    }
    description = "Date (without time)"

    def __init__(
        self, *, auto_now: bool = False, auto_now_add: bool = False, **kwargs: Any
    ):
        self.auto_now, self.auto_now_add = auto_now, auto_now_add
        if auto_now or auto_now_add:
            kwargs["required"] = False
        super().__init__(**kwargs)

    def _check_fix_default_value(self) -> list[PreflightResult]:
        """
        Warn that using an actual date or datetime value is probably wrong;
        it's only evaluated on server startup.
        """
        if not self.has_default():
            return []

        value = self.default
        if isinstance(value, datetime.datetime):
            value = _to_naive(value).date()
        elif isinstance(value, datetime.date):
            pass
        else:
            # No explicit date / datetime value -- no checks necessary
            return []
        # At this point, value is a date object.
        return self._check_if_value_fixed(value)

    def deconstruct(self) -> tuple[str, str, list[Any], dict[str, Any]]:
        name, path, args, kwargs = super().deconstruct()
        if self.auto_now:
            kwargs["auto_now"] = True
        if self.auto_now_add:
            kwargs["auto_now_add"] = True
        if self.auto_now or self.auto_now_add:
            del kwargs["required"]
        return name, path, args, kwargs

    def get_internal_type(self) -> str:
        return "DateField"

    def to_python(self, value: Any) -> Any:
        if value is None:
            return value
        if isinstance(value, datetime.datetime):
            if timezone.is_aware(value):
                # Convert aware datetimes to the default time zone
                # before casting them to dates (#17742).
                default_timezone = timezone.get_default_timezone()
                value = timezone.make_naive(value, default_timezone)
            return value.date()
        if isinstance(value, datetime.date):
            return value

        try:
            parsed = parse_date(value)
            if parsed is not None:
                return parsed
        except ValueError:
            raise exceptions.ValidationError(
                self.error_messages["invalid_date"],
                code="invalid_date",
                params={"value": value},
            )

        raise exceptions.ValidationError(
            self.error_messages["invalid"],
            code="invalid",
            params={"value": value},
        )

    def pre_save(self, model_instance: Any, add: bool) -> Any:
        if self.auto_now or (self.auto_now_add and add):
            value = datetime.date.today()
            setattr(model_instance, self.attname, value)
            return value
        else:
            return super().pre_save(model_instance, add)

    def get_prep_value(self, value: Any) -> Any:
        value = super().get_prep_value(value)
        return self.to_python(value)

    def get_db_prep_value(
        self, value: Any, connection: BaseDatabaseWrapper, prepared: bool = False
    ) -> Any:
        # Casts dates into the format expected by the backend
        if not prepared:
            value = self.get_prep_value(value)
        return connection.ops.adapt_datefield_value(value)

    def value_to_string(self, obj: Any) -> str:
        val = self.value_from_object(obj)
        return "" if val is None else val.isoformat()


class DateTimeField(DateField):
    empty_strings_allowed = False
    default_error_messages = {
        "invalid": '"%(value)s" value has an invalid format. It must be in YYYY-MM-DD HH:MM[:ss[.uuuuuu]][TZ] format.',
        "invalid_date": '"%(value)s" value has the correct format (YYYY-MM-DD) but it is an invalid date.',
        "invalid_datetime": '"%(value)s" value has the correct format (YYYY-MM-DD HH:MM[:ss[.uuuuuu]][TZ]) but it is an invalid date/time.',
    }
    description = "Date (with time)"

    # __init__ is inherited from DateField

    def _check_fix_default_value(self) -> list[PreflightResult]:
        """
        Warn that using an actual date or datetime value is probably wrong;
        it's only evaluated on server startup.
        """
        if not self.has_default():
            return []

        value = self.default
        if isinstance(value, datetime.datetime | datetime.date):
            return self._check_if_value_fixed(value)
        # No explicit date / datetime value -- no checks necessary.
        return []

    def get_internal_type(self) -> str:
        return "DateTimeField"

    def to_python(self, value: Any) -> Any:
        if value is None:
            return value
        if isinstance(value, datetime.datetime):
            return value
        if isinstance(value, datetime.date):
            value = datetime.datetime(value.year, value.month, value.day)

            # For backwards compatibility, interpret naive datetimes in
            # local time. This won't work during DST change, but we can't
            # do much about it, so we let the exceptions percolate up the
            # call stack.
            warnings.warn(
                f"DateTimeField {self.model.__name__}.{self.name} received a naive datetime "
                f"({value}) while time zone support is active.",
                RuntimeWarning,
            )
            default_timezone = timezone.get_default_timezone()
            value = timezone.make_aware(value, default_timezone)

            return value

        try:
            parsed = parse_datetime(value)
            if parsed is not None:
                return parsed
        except ValueError:
            raise exceptions.ValidationError(
                self.error_messages["invalid_datetime"],
                code="invalid_datetime",
                params={"value": value},
            )

        try:
            parsed = parse_date(value)
            if parsed is not None:
                return datetime.datetime(parsed.year, parsed.month, parsed.day)
        except ValueError:
            raise exceptions.ValidationError(
                self.error_messages["invalid_date"],
                code="invalid_date",
                params={"value": value},
            )

        raise exceptions.ValidationError(
            self.error_messages["invalid"],
            code="invalid",
            params={"value": value},
        )

    def pre_save(self, model_instance: Any, add: bool) -> Any:
        if self.auto_now or (self.auto_now_add and add):
            value = timezone.now()
            setattr(model_instance, self.attname, value)
            return value
        else:
            return super().pre_save(model_instance, add)

    def get_prep_value(self, value: Any) -> Any:
        value = super().get_prep_value(value)
        value = self.to_python(value)
        if value is not None and timezone.is_naive(value):
            # For backwards compatibility, interpret naive datetimes in local
            # time. This won't work during DST change, but we can't do much
            # about it, so we let the exceptions percolate up the call stack.
            try:
                name = f"{self.model.__name__}.{self.name}"
            except AttributeError:
                name = "(unbound)"
            warnings.warn(
                f"DateTimeField {name} received a naive datetime ({value})"
                " while time zone support is active.",
                RuntimeWarning,
            )
            default_timezone = timezone.get_default_timezone()
            value = timezone.make_aware(value, default_timezone)
        return value

    def get_db_prep_value(
        self, value: Any, connection: BaseDatabaseWrapper, prepared: bool = False
    ) -> Any:
        # Casts datetimes into the format expected by the backend
        if not prepared:
            value = self.get_prep_value(value)
        return connection.ops.adapt_datetimefield_value(value)

    def value_to_string(self, obj: Any) -> str:
        val = self.value_from_object(obj)
        return "" if val is None else val.isoformat()


class DecimalField(Field[decimal.Decimal]):
    empty_strings_allowed = False
    default_error_messages = {
        "invalid": '"%(value)s" value must be a decimal number.',
    }
    description = "Decimal number"

    def __init__(
        self,
        *,
        max_digits: int | None = None,
        decimal_places: int | None = None,
        **kwargs: Any,
    ):
        self.max_digits, self.decimal_places = max_digits, decimal_places
        super().__init__(**kwargs)

    def preflight(self, **kwargs: Any) -> list[PreflightResult]:
        errors = super().preflight(**kwargs)

        digits_errors = [
            *self._check_decimal_places(),
            *self._check_max_digits(),
        ]
        if not digits_errors:
            errors.extend(self._check_decimal_places_and_max_digits())
        else:
            errors.extend(digits_errors)
        return errors

    def _check_decimal_places(self) -> list[PreflightResult]:
        try:
            decimal_places = int(self.decimal_places)
            if decimal_places < 0:
                raise ValueError()
        except TypeError:
            return [
                PreflightResult(
                    fix="DecimalFields must define a 'decimal_places' attribute.",
                    obj=self,
                    id="fields.decimalfield_missing_decimal_places",
                )
            ]
        except ValueError:
            return [
                PreflightResult(
                    fix="'decimal_places' must be a non-negative integer.",
                    obj=self,
                    id="fields.decimalfield_invalid_decimal_places",
                )
            ]
        else:
            return []

    def _check_max_digits(self) -> list[PreflightResult]:
        try:
            max_digits = int(self.max_digits)
            if max_digits <= 0:
                raise ValueError()
        except TypeError:
            return [
                PreflightResult(
                    fix="DecimalFields must define a 'max_digits' attribute.",
                    obj=self,
                    id="fields.decimalfield_missing_max_digits",
                )
            ]
        except ValueError:
            return [
                PreflightResult(
                    fix="'max_digits' must be a positive integer.",
                    obj=self,
                    id="fields.decimalfield_invalid_max_digits",
                )
            ]
        else:
            return []

    def _check_decimal_places_and_max_digits(self) -> list[PreflightResult]:
        if int(self.decimal_places) > int(self.max_digits):
            return [
                PreflightResult(
                    fix="'max_digits' must be greater or equal to 'decimal_places'.",
                    obj=self,
                    id="fields.decimalfield_decimal_places_exceeds_max_digits",
                )
            ]
        return []

    @cached_property
    def validators(self) -> list[Callable[..., Any]]:
        return super().validators + [
            validators.DecimalValidator(self.max_digits, self.decimal_places)
        ]

    @cached_property
    def context(self) -> decimal.Context:
        return decimal.Context(prec=self.max_digits)

    def deconstruct(self) -> tuple[str, str, list[Any], dict[str, Any]]:
        name, path, args, kwargs = super().deconstruct()
        if self.max_digits is not None:
            kwargs["max_digits"] = self.max_digits
        if self.decimal_places is not None:
            kwargs["decimal_places"] = self.decimal_places
        return name, path, args, kwargs

    def get_internal_type(self) -> str:
        return "DecimalField"

    def to_python(self, value: Any) -> Any:
        if value is None:
            return value
        try:
            if isinstance(value, float):
                decimal_value = self.context.create_decimal_from_float(value)
            else:
                decimal_value = decimal.Decimal(value)
        except (decimal.InvalidOperation, TypeError, ValueError):
            raise exceptions.ValidationError(
                self.error_messages["invalid"],
                code="invalid",
                params={"value": value},
            )
        if not decimal_value.is_finite():
            raise exceptions.ValidationError(
                self.error_messages["invalid"],
                code="invalid",
                params={"value": value},
            )
        return decimal_value

    def get_db_prep_value(
        self, value: Any, connection: BaseDatabaseWrapper, prepared: bool = False
    ) -> Any:
        if not prepared:
            value = self.get_prep_value(value)
        if hasattr(value, "as_sql"):
            return value
        return connection.ops.adapt_decimalfield_value(
            value, self.max_digits, self.decimal_places
        )

    def get_prep_value(self, value: Any) -> Any:
        value = super().get_prep_value(value)
        return self.to_python(value)


class DurationField(Field[datetime.timedelta]):
    """
    Store timedelta objects.

    Use interval on PostgreSQL, INTERVAL DAY TO SECOND on Oracle, and bigint
    of microseconds on other databases.
    """

    empty_strings_allowed = False
    default_error_messages = {
        "invalid": '"%(value)s" value has an invalid format. It must be in [DD] [[HH:]MM:]ss[.uuuuuu] format.',
    }
    description = "Duration"

    def get_internal_type(self) -> str:
        return "DurationField"

    def to_python(self, value: Any) -> Any:
        if value is None:
            return value
        if isinstance(value, datetime.timedelta):
            return value
        try:
            parsed = parse_duration(value)
        except ValueError:
            pass
        else:
            if parsed is not None:
                return parsed

        raise exceptions.ValidationError(
            self.error_messages["invalid"],
            code="invalid",
            params={"value": value},
        )

    def get_db_prep_value(
        self, value: Any, connection: BaseDatabaseWrapper, prepared: bool = False
    ) -> Any:
        if connection.features.has_native_duration_field:
            return value
        if value is None:
            return None
        return duration_microseconds(value)

    def get_db_converters(
        self, connection: BaseDatabaseWrapper
    ) -> list[Callable[..., Any]]:
        converters = []
        if not connection.features.has_native_duration_field:
            converters.append(connection.ops.convert_durationfield_value)
        return converters + super().get_db_converters(connection)

    def value_to_string(self, obj: Any) -> str:
        val = self.value_from_object(obj)
        return "" if val is None else duration_string(val)


class EmailField(CharField):
    default_validators = [validators.validate_email]
    description = "Email address"

    def __init__(self, **kwargs: Any):
        # max_length=254 to be compliant with RFCs 3696 and 5321
        kwargs.setdefault("max_length", 254)
        super().__init__(**kwargs)

    def deconstruct(self) -> tuple[str, str, list[Any], dict[str, Any]]:
        name, path, args, kwargs = super().deconstruct()
        # We do not exclude max_length if it matches default as we want to change
        # the default in future.
        return name, path, args, kwargs


class FloatField(Field[float]):
    empty_strings_allowed = False
    default_error_messages = {
        "invalid": '"%(value)s" value must be a float.',
    }
    description = "Floating point number"

    def get_prep_value(self, value: Any) -> Any:
        value = super().get_prep_value(value)
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError) as e:
            raise e.__class__(
                f"Field '{self.name}' expected a number but got {value!r}.",
            ) from e

    def get_internal_type(self) -> str:
        return "FloatField"

    def to_python(self, value: Any) -> Any:
        if value is None:
            return value
        try:
            return float(value)
        except (TypeError, ValueError):
            raise exceptions.ValidationError(
                self.error_messages["invalid"],
                code="invalid",
                params={"value": value},
            )


class IntegerField(Field[int]):
    empty_strings_allowed = False
    default_error_messages = {
        "invalid": '"%(value)s" value must be an integer.',
    }
    description = "Integer"

    def preflight(self, **kwargs: Any) -> list[PreflightResult]:
        return [
            *super().preflight(**kwargs),
            *self._check_max_length_warning(),
        ]

    def _check_max_length_warning(self) -> list[PreflightResult]:
        if self.max_length is not None:
            return [
                PreflightResult(
                    fix=f"'max_length' is ignored when used with {self.__class__.__name__}. Remove 'max_length' from field.",
                    obj=self,
                    id="fields.max_length_ignored",
                    warning=True,
                )
            ]
        return []

    @cached_property
    def validators(self) -> list[Callable[..., Any]]:
        # These validators can't be added at field initialization time since
        # they're based on values retrieved from the database connection.
        validators_ = super().validators
        internal_type = self.get_internal_type()
        min_value, max_value = db_connection.ops.integer_field_range(internal_type)
        if min_value is not None and not any(
            (
                isinstance(validator, validators.MinValueValidator)
                and (
                    validator.limit_value()
                    if callable(validator.limit_value)
                    else validator.limit_value
                )
                >= min_value
            )
            for validator in validators_
        ):
            validators_.append(validators.MinValueValidator(min_value))
        if max_value is not None and not any(
            (
                isinstance(validator, validators.MaxValueValidator)
                and (
                    validator.limit_value()
                    if callable(validator.limit_value)
                    else validator.limit_value
                )
                <= max_value
            )
            for validator in validators_
        ):
            validators_.append(validators.MaxValueValidator(max_value))
        return validators_

    def get_prep_value(self, value: Any) -> Any:
        value = super().get_prep_value(value)
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError) as e:
            raise e.__class__(
                f"Field '{self.name}' expected a number but got {value!r}.",
            ) from e

    def get_db_prep_value(
        self, value: Any, connection: BaseDatabaseWrapper, prepared: bool = False
    ) -> Any:
        value = super().get_db_prep_value(value, connection, prepared)
        return connection.ops.adapt_integerfield_value(value, self.get_internal_type())

    def get_internal_type(self) -> str:
        return "IntegerField"

    def to_python(self, value: Any) -> Any:
        if value is None:
            return value
        try:
            return int(value)
        except (TypeError, ValueError):
            raise exceptions.ValidationError(
                self.error_messages["invalid"],
                code="invalid",
                params={"value": value},
            )


class BigIntegerField(IntegerField):
    description = "Big (8 byte) integer"

    def get_internal_type(self) -> str:
        return "BigIntegerField"


class SmallIntegerField(IntegerField):
    description = "Small integer"

    def get_internal_type(self) -> str:
        return "SmallIntegerField"


class GenericIPAddressField(Field[str]):
    empty_strings_allowed = False
    description = "IP address"
    default_error_messages = {}

    def __init__(
        self,
        *,
        protocol: str = "both",
        unpack_ipv4: bool = False,
        **kwargs: Any,
    ):
        self.unpack_ipv4 = unpack_ipv4
        self.protocol = protocol
        (
            self.default_validators,
            invalid_error_message,
        ) = validators.ip_address_validators(protocol, unpack_ipv4)
        self.default_error_messages["invalid"] = invalid_error_message
        kwargs["max_length"] = 39
        super().__init__(**kwargs)

    def preflight(self, **kwargs: Any) -> list[PreflightResult]:
        return [
            *super().preflight(**kwargs),
            *self._check_required_and_null_values(),
        ]

    def _check_required_and_null_values(self) -> list[PreflightResult]:
        if not getattr(self, "allow_null", False) and not getattr(
            self, "required", True
        ):
            return [
                PreflightResult(
                    fix="GenericIPAddressFields cannot have required=False if allow_null=False, "
                    "as blank values are stored as nulls.",
                    obj=self,
                    id="fields.generic_ip_field_null_blank_config",
                )
            ]
        return []

    def deconstruct(self) -> tuple[str, str, list[Any], dict[str, Any]]:
        name, path, args, kwargs = super().deconstruct()
        if self.unpack_ipv4 is not False:
            kwargs["unpack_ipv4"] = self.unpack_ipv4
        if self.protocol != "both":
            kwargs["protocol"] = self.protocol
        if kwargs.get("max_length") == 39:
            del kwargs["max_length"]
        return name, path, args, kwargs

    def get_internal_type(self) -> str:
        return "GenericIPAddressField"

    def to_python(self, value: Any) -> Any:
        if value is None:
            return None
        if not isinstance(value, str):
            value = str(value)
        value = value.strip()
        if ":" in value:
            return clean_ipv6_address(
                value, self.unpack_ipv4, self.error_messages["invalid"]
            )
        return value

    def get_db_prep_value(
        self, value: Any, connection: BaseDatabaseWrapper, prepared: bool = False
    ) -> Any:
        if not prepared:
            value = self.get_prep_value(value)
        return connection.ops.adapt_ipaddressfield_value(value)

    def get_prep_value(self, value: Any) -> Any:
        value = super().get_prep_value(value)
        if value is None:
            return None
        if value and ":" in value:
            try:
                return clean_ipv6_address(value, self.unpack_ipv4)
            except exceptions.ValidationError:
                pass
        return str(value)


class PositiveIntegerRelDbTypeMixin:
    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        if not hasattr(cls, "integer_field_class"):
            cls.integer_field_class = next(
                (
                    parent
                    for parent in cls.__mro__[1:]
                    if issubclass(parent, IntegerField)
                ),
                None,
            )

    def rel_db_type(self, connection: BaseDatabaseWrapper) -> str | None:
        """
        Return the data type that a related field pointing to this field should
        use. In most cases, a foreign key pointing to a positive integer
        primary key will have an integer column data type but some databases
        (e.g. MySQL) have an unsigned integer type. In that case
        (related_fields_match_type=True), the primary key should return its
        db_type.
        """
        if connection.features.related_fields_match_type:
            return self.db_type(connection)
        else:
            return self.integer_field_class().db_type(connection=connection)


class PositiveBigIntegerField(PositiveIntegerRelDbTypeMixin, BigIntegerField):
    description = "Positive big integer"

    def get_internal_type(self) -> str:
        return "PositiveBigIntegerField"


class PositiveIntegerField(PositiveIntegerRelDbTypeMixin, IntegerField):
    description = "Positive integer"

    def get_internal_type(self) -> str:
        return "PositiveIntegerField"


class PositiveSmallIntegerField(PositiveIntegerRelDbTypeMixin, SmallIntegerField):
    description = "Positive small integer"

    def get_internal_type(self) -> str:
        return "PositiveSmallIntegerField"


class TextField(Field[str]):
    description = "Text"

    def __init__(self, *, db_collation: str | None = None, **kwargs: Any):
        super().__init__(**kwargs)
        self.db_collation = db_collation

    def preflight(self, **kwargs: Any) -> list[PreflightResult]:
        return [
            *super().preflight(**kwargs),
            *self._check_db_collation(),
        ]

    def _check_db_collation(self) -> list[PreflightResult]:
        errors = []
        if not (
            self.db_collation is None
            or "supports_collation_on_textfield"
            in self.model.model_options.required_db_features
            or db_connection.features.supports_collation_on_textfield
        ):
            errors.append(
                PreflightResult(
                    fix=f"{db_connection.display_name} does not support a database collation on "
                    "TextFields.",
                    obj=self,
                    id="fields.db_collation_unsupported",
                ),
            )
        return errors

    def db_parameters(self, connection: BaseDatabaseWrapper) -> dict[str, Any]:
        db_params = super().db_parameters(connection)
        db_params["collation"] = self.db_collation
        return db_params

    def get_internal_type(self) -> str:
        return "TextField"

    def to_python(self, value: Any) -> Any:
        if isinstance(value, str) or value is None:
            return value
        return str(value)

    def get_prep_value(self, value: Any) -> Any:
        value = super().get_prep_value(value)
        return self.to_python(value)

    def deconstruct(self) -> tuple[str, str, list[Any], dict[str, Any]]:
        name, path, args, kwargs = super().deconstruct()
        if self.db_collation:
            kwargs["db_collation"] = self.db_collation
        return name, path, args, kwargs


class TimeField(DateTimeCheckMixin, Field[datetime.time]):
    empty_strings_allowed = False
    default_error_messages = {
        "invalid": '"%(value)s" value has an invalid format. It must be in HH:MM[:ss[.uuuuuu]] format.',
        "invalid_time": '"%(value)s" value has the correct format (HH:MM[:ss[.uuuuuu]]) but it is an invalid time.',
    }
    description = "Time"

    def __init__(
        self, *, auto_now: bool = False, auto_now_add: bool = False, **kwargs: Any
    ):
        self.auto_now, self.auto_now_add = auto_now, auto_now_add
        if auto_now or auto_now_add:
            kwargs["required"] = False
        super().__init__(**kwargs)

    def _check_fix_default_value(self) -> list[PreflightResult]:
        """
        Warn that using an actual date or datetime value is probably wrong;
        it's only evaluated on server startup.
        """
        if not self.has_default():
            return []

        value = self.default
        if isinstance(value, datetime.datetime):
            now = None
        elif isinstance(value, datetime.time):
            now = _get_naive_now()
            # This will not use the right date in the race condition where now
            # is just before the date change and value is just past 0:00.
            value = datetime.datetime.combine(now.date(), value)
        else:
            # No explicit time / datetime value -- no checks necessary
            return []
        # At this point, value is a datetime object.
        return self._check_if_value_fixed(value, now=now)

    def deconstruct(self) -> tuple[str, str, list[Any], dict[str, Any]]:
        name, path, args, kwargs = super().deconstruct()
        if self.auto_now is not False:
            kwargs["auto_now"] = self.auto_now
        if self.auto_now_add is not False:
            kwargs["auto_now_add"] = self.auto_now_add
        if self.auto_now or self.auto_now_add:
            del kwargs["required"]
        return name, path, args, kwargs

    def get_internal_type(self) -> str:
        return "TimeField"

    def to_python(self, value: Any) -> Any:
        if value is None:
            return None
        if isinstance(value, datetime.time):
            return value
        if isinstance(value, datetime.datetime):
            # Not usually a good idea to pass in a datetime here (it loses
            # information), but this can be a side-effect of interacting with a
            # database backend (e.g. Oracle), so we'll be accommodating.
            return value.time()

        try:
            parsed = parse_time(value)
            if parsed is not None:
                return parsed
        except ValueError:
            raise exceptions.ValidationError(
                self.error_messages["invalid_time"],
                code="invalid_time",
                params={"value": value},
            )

        raise exceptions.ValidationError(
            self.error_messages["invalid"],
            code="invalid",
            params={"value": value},
        )

    def pre_save(self, model_instance: Any, add: bool) -> Any:
        if self.auto_now or (self.auto_now_add and add):
            value = datetime.datetime.now().time()
            setattr(model_instance, self.attname, value)
            return value
        else:
            return super().pre_save(model_instance, add)

    def get_prep_value(self, value: Any) -> Any:
        value = super().get_prep_value(value)
        return self.to_python(value)

    def get_db_prep_value(
        self, value: Any, connection: BaseDatabaseWrapper, prepared: bool = False
    ) -> Any:
        # Casts times into the format expected by the backend
        if not prepared:
            value = self.get_prep_value(value)
        return connection.ops.adapt_timefield_value(value)

    def value_to_string(self, obj: Any) -> str:
        val = self.value_from_object(obj)
        return "" if val is None else val.isoformat()


class URLField(CharField):
    default_validators = [validators.URLValidator()]
    description = "URL"

    def __init__(self, **kwargs: Any):
        kwargs.setdefault("max_length", 200)
        super().__init__(**kwargs)

    def deconstruct(self) -> tuple[str, str, list[Any], dict[str, Any]]:
        name, path, args, kwargs = super().deconstruct()
        if kwargs.get("max_length") == 200:
            del kwargs["max_length"]
        return name, path, args, kwargs


class BinaryField(Field[bytes | memoryview]):
    description = "Raw binary data"
    empty_values = [None, b""]

    def __init__(self, **kwargs: Any):
        super().__init__(**kwargs)
        if self.max_length is not None:
            self.validators.append(validators.MaxLengthValidator(self.max_length))

    def preflight(self, **kwargs: Any) -> list[PreflightResult]:
        return [*super().preflight(**kwargs), *self._check_str_default_value()]

    def _check_str_default_value(self) -> list[PreflightResult]:
        if self.has_default() and isinstance(self.default, str):
            return [
                PreflightResult(
                    fix="BinaryField's default cannot be a string. Use bytes "
                    "content instead.",
                    obj=self,
                    id="fields.filefield_upload_to_not_callable",
                )
            ]
        return []

    def get_internal_type(self) -> str:
        return "BinaryField"

    def get_placeholder(
        self, value: Any, compiler: SQLCompiler, connection: BaseDatabaseWrapper
    ) -> Any:
        return connection.ops.binary_placeholder_sql(value)

    def get_default(self) -> Any:
        if self.has_default() and not callable(self.default):
            return self.default
        default = super().get_default()
        if default == "":
            return b""
        return default

    def get_db_prep_value(
        self, value: Any, connection: BaseDatabaseWrapper, prepared: bool = False
    ) -> Any:
        value = super().get_db_prep_value(value, connection, prepared)
        if value is not None:
            return connection.Database.Binary(value)  # type: ignore[attr-defined]
        return value

    def value_to_string(self, obj: Any) -> str:
        """Binary data is serialized as base64"""
        return b64encode(self.value_from_object(obj)).decode("ascii")

    def to_python(self, value: Any) -> Any:
        # If it's a string, it should be base64-encoded data
        if isinstance(value, str):
            return memoryview(b64decode(value.encode("ascii")))
        return value


class UUIDField(Field[uuid.UUID]):
    default_error_messages = {
        "invalid": '"%(value)s" is not a valid UUID.',
    }
    description = "Universally unique identifier"
    empty_strings_allowed = False

    def __init__(self, **kwargs: Any):
        kwargs["max_length"] = 32
        super().__init__(**kwargs)

    def deconstruct(self) -> tuple[str, str, list[Any], dict[str, Any]]:
        name, path, args, kwargs = super().deconstruct()
        del kwargs["max_length"]
        return name, path, args, kwargs

    def get_internal_type(self) -> str:
        return "UUIDField"

    def get_prep_value(self, value: Any) -> Any:
        value = super().get_prep_value(value)
        return self.to_python(value)

    def get_db_prep_value(
        self, value: Any, connection: BaseDatabaseWrapper, prepared: bool = False
    ) -> Any:
        if value is None:
            return None
        if not isinstance(value, uuid.UUID):
            value = self.to_python(value)

        if connection.features.has_native_uuid_field:
            return value
        return value.hex

    def to_python(self, value: Any) -> Any:
        if value is not None and not isinstance(value, uuid.UUID):
            input_form = "int" if isinstance(value, int) else "hex"
            try:
                return uuid.UUID(**{input_form: value})
            except (AttributeError, ValueError):
                raise exceptions.ValidationError(
                    self.error_messages["invalid"],
                    code="invalid",
                    params={"value": value},
                )
        return value


class PrimaryKeyField(BigIntegerField):
    db_returning = True

    def __init__(self):
        super().__init__(required=False)
        self.primary_key = True
        self.auto_created = True
        # Adjust creation counter for auto-created fields
        # We need to undo the counter increment from Field.__init__ and use the auto counter
        Field.creation_counter -= 1  # Undo the increment
        self.creation_counter = Field.auto_creation_counter
        Field.auto_creation_counter -= 1

    def preflight(self, **kwargs: Any) -> list[PreflightResult]:
        errors = super().preflight(**kwargs)
        # Remove the reserved_field_name_id error for 'id' field name since PrimaryKeyField is allowed to use it
        errors = [e for e in errors if e.id != "fields.reserved_field_name_id"]
        return errors

    def deconstruct(self) -> tuple[str, str, list[Any], dict[str, Any]]:
        # PrimaryKeyField takes no parameters, so we return an empty kwargs dict
        return (self.name, "plain.models.PrimaryKeyField", [], {})

    def validate(self, value: Any, model_instance: Any) -> None:
        pass

    def get_db_prep_value(
        self, value: Any, connection: BaseDatabaseWrapper, prepared: bool = False
    ) -> Any:
        if not prepared:
            value = self.get_prep_value(value)
            value = connection.ops.validate_autopk_value(value)
        return value

    def get_internal_type(self) -> str:
        return "PrimaryKeyField"

    def rel_db_type(self, connection: BaseDatabaseWrapper) -> str | None:
        return BigIntegerField().db_type(connection=connection)
