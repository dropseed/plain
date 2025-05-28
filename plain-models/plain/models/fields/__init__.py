import collections.abc
import copy
import datetime
import decimal
import enum
import operator
import uuid
import warnings
from base64 import b64decode, b64encode
from functools import cached_property, partialmethod, total_ordering

from plain import exceptions, preflight, validators
from plain.models.constants import LOOKUP_SEP
from plain.models.db import connection, connections, router
from plain.models.enums import ChoicesMeta
from plain.models.query_utils import DeferredAttribute, RegisterLookupMixin
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

__all__ = [
    "AutoField",
    "BLANK_CHOICE_DASH",
    "BigAutoField",
    "BigIntegerField",
    "BinaryField",
    "BooleanField",
    "CharField",
    "CommaSeparatedIntegerField",
    "DateField",
    "DateTimeField",
    "DecimalField",
    "DurationField",
    "EmailField",
    "Empty",
    "Field",
    "FloatField",
    "GenericIPAddressField",
    "IPAddressField",
    "IntegerField",
    "NOT_PROVIDED",
    "NullBooleanField",
    "PositiveBigIntegerField",
    "PositiveIntegerField",
    "PositiveSmallIntegerField",
    "SmallAutoField",
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


def _load_field(package_label, model_name, field_name):
    return models_registry.get_model(package_label, model_name)._meta.get_field(
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
# attname. For example, this gets the primary key value of object "obj":
#
#     getattr(obj, opts.pk.attname)


def _empty(of_cls):
    new = Empty()
    new.__class__ = of_cls
    return new


def return_None():
    return None


@total_ordering
class Field(RegisterLookupMixin):
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
    system_check_deprecated_details = None
    system_check_removed_details = None

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

    descriptor_class = DeferredAttribute

    # Generic field type description, usually overridden by subclasses
    def _description(self):
        return f"Field of type: {self.__class__.__name__}"

    description = property(_description)

    def __init__(
        self,
        *,
        primary_key=False,
        max_length=None,
        required=True,
        allow_null=False,
        rel=None,
        default=NOT_PROVIDED,
        choices=None,
        db_column=None,
        auto_created=False,
        validators=(),
        error_messages=None,
        db_comment=None,
    ):
        self.name = None  # Set by set_attributes_from_name
        self.primary_key = primary_key
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
        self.auto_created = auto_created

        # Adjust the appropriate creation counter, and save our local copy.
        if auto_created:
            self.creation_counter = Field.auto_creation_counter
            Field.auto_creation_counter -= 1
        else:
            self.creation_counter = Field.creation_counter
            Field.creation_counter += 1

        self._validators = list(validators)  # Store for deconstruction later

        self._error_messages = error_messages  # Store for deconstruction later

    def __str__(self):
        """
        Return "package_label.model_label.field_name" for fields attached to
        models.
        """
        if not hasattr(self, "model"):
            return super().__str__()
        model = self.model
        return f"{model._meta.label}.{self.name}"

    def __repr__(self):
        """Display the module, class, and name of the field."""
        path = f"{self.__class__.__module__}.{self.__class__.__qualname__}"
        name = getattr(self, "name", None)
        if name is not None:
            return f"<{path}: {name}>"
        return f"<{path}>"

    def check(self, **kwargs):
        return [
            *self._check_field_name(),
            *self._check_choices(),
            *self._check_db_comment(**kwargs),
            *self._check_null_allowed_for_primary_keys(),
            *self._check_backend_specific_checks(**kwargs),
            *self._check_validators(),
            *self._check_deprecation_details(),
        ]

    def _check_field_name(self):
        """
        Check if field name is valid, i.e. 1) does not end with an
        underscore, 2) does not contain "__" and 3) is not "pk".
        """
        if self.name.endswith("_"):
            return [
                preflight.Error(
                    "Field names must not end with an underscore.",
                    obj=self,
                    id="fields.E001",
                )
            ]
        elif LOOKUP_SEP in self.name:
            return [
                preflight.Error(
                    f'Field names must not contain "{LOOKUP_SEP}".',
                    obj=self,
                    id="fields.E002",
                )
            ]
        elif self.name == "pk":
            return [
                preflight.Error(
                    "'pk' is a reserved word that cannot be used as a field name.",
                    obj=self,
                    id="fields.E003",
                )
            ]
        else:
            return []

    @classmethod
    def _choices_is_value(cls, value):
        return isinstance(value, str | Promise) or not is_iterable(value)

    def _check_choices(self):
        if not self.choices:
            return []

        if not is_iterable(self.choices) or isinstance(self.choices, str):
            return [
                preflight.Error(
                    "'choices' must be an iterable (e.g., a list or tuple).",
                    obj=self,
                    id="fields.E004",
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
                    preflight.Error(
                        "'max_length' is too small to fit the longest value "  # noqa: UP031
                        "in 'choices' (%d characters)." % choice_max_length,
                        obj=self,
                        id="fields.E009",
                    ),
                ]
            return []

        return [
            preflight.Error(
                "'choices' must be an iterable containing "
                "(actual value, human readable name) tuples.",
                obj=self,
                id="fields.E005",
            )
        ]

    def _check_db_comment(self, databases=None, **kwargs):
        if not self.db_comment or not databases:
            return []
        errors = []
        for db in databases:
            if not router.allow_migrate_model(db, self.model):
                continue
            connection = connections[db]
            if not (
                connection.features.supports_comments
                or "supports_comments" in self.model._meta.required_db_features
            ):
                errors.append(
                    preflight.Warning(
                        f"{connection.display_name} does not support comments on "
                        f"columns (db_comment).",
                        obj=self,
                        id="fields.W163",
                    )
                )
        return errors

    def _check_null_allowed_for_primary_keys(self):
        if (
            self.primary_key
            and self.allow_null
            and not connection.features.interprets_empty_strings_as_nulls
        ):
            # We cannot reliably check this for backends like Oracle which
            # consider NULL and '' to be equal (and thus set up
            # character-based fields a little differently).
            return [
                preflight.Error(
                    "Primary keys must not have allow_null=True.",
                    hint=(
                        "Set allow_null=False on the field, or "
                        "remove primary_key=True argument."
                    ),
                    obj=self,
                    id="fields.E007",
                )
            ]
        else:
            return []

    def _check_backend_specific_checks(self, databases=None, **kwargs):
        if databases is None:
            return []
        errors = []
        for alias in databases:
            if router.allow_migrate_model(alias, self.model):
                errors.extend(connections[alias].validation.check_field(self, **kwargs))
        return errors

    def _check_validators(self):
        errors = []
        for i, validator in enumerate(self.validators):
            if not callable(validator):
                errors.append(
                    preflight.Error(
                        "All 'validators' must be callable.",
                        hint=(
                            f"validators[{i}] ({repr(validator)}) isn't a function or "
                            "instance of a validator class."
                        ),
                        obj=self,
                        id="fields.E008",
                    )
                )
        return errors

    def _check_deprecation_details(self):
        if self.system_check_removed_details is not None:
            return [
                preflight.Error(
                    self.system_check_removed_details.get(
                        "msg",
                        f"{self.__class__.__name__} has been removed except for support in historical "
                        "migrations.",
                    ),
                    hint=self.system_check_removed_details.get("hint"),
                    obj=self,
                    id=self.system_check_removed_details.get("id", "fields.EXXX"),
                )
            ]
        elif self.system_check_deprecated_details is not None:
            return [
                preflight.Warning(
                    self.system_check_deprecated_details.get(
                        "msg", f"{self.__class__.__name__} has been deprecated."
                    ),
                    hint=self.system_check_deprecated_details.get("hint"),
                    obj=self,
                    id=self.system_check_deprecated_details.get("id", "fields.WXXX"),
                )
            ]
        return []

    def get_col(self, alias, output_field=None):
        if alias == self.model._meta.db_table and (
            output_field is None or output_field == self
        ):
            return self.cached_col
        from plain.models.expressions import Col

        return Col(alias, self, output_field)

    @cached_property
    def cached_col(self):
        from plain.models.expressions import Col

        return Col(self.model._meta.db_table, self)

    def select_format(self, compiler, sql, params):
        """
        Custom format for select clauses. For example, GIS columns need to be
        selected as AsText(table.col) on MySQL as the table.col data can't be
        used by Plain.
        """
        return sql, params

    def deconstruct(self):
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
            "primary_key": False,
            "max_length": None,
            "required": True,
            "allow_null": False,
            "default": NOT_PROVIDED,
            "choices": None,
            "db_column": None,
            "db_comment": None,
            "auto_created": False,
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

    def clone(self):
        """
        Uses deconstruct() to clone a new copy of this Field.
        Will not preserve any class attachments/attribute names.
        """
        name, path, args, kwargs = self.deconstruct()
        return self.__class__(*args, **kwargs)

    def __eq__(self, other):
        # Needed for @total_ordering
        if isinstance(other, Field):
            return self.creation_counter == other.creation_counter and getattr(
                self, "model", None
            ) == getattr(other, "model", None)
        return NotImplemented

    def __lt__(self, other):
        # This is needed because bisect does not take a comparison function.
        # Order by creation_counter first for backward compatibility.
        if isinstance(other, Field):
            if (
                self.creation_counter != other.creation_counter
                or not hasattr(self, "model")
                and not hasattr(other, "model")
            ):
                return self.creation_counter < other.creation_counter
            elif hasattr(self, "model") != hasattr(other, "model"):
                return not hasattr(self, "model")  # Order no-model fields first
            else:
                # creation_counter's are equal, compare only models.
                return (self.model._meta.package_label, self.model._meta.model_name) < (
                    other.model._meta.package_label,
                    other.model._meta.model_name,
                )
        return NotImplemented

    def __hash__(self):
        return hash(self.creation_counter)

    def __deepcopy__(self, memodict):
        # We don't have to deepcopy very much here, since most things are not
        # intended to be altered after initial creation.
        obj = copy.copy(self)
        if self.remote_field:
            obj.remote_field = copy.copy(self.remote_field)
            if hasattr(self.remote_field, "field") and self.remote_field.field is self:
                obj.remote_field.field = obj
        memodict[id(self)] = obj
        return obj

    def __copy__(self):
        # We need to avoid hitting __reduce__, so define this
        # slightly weird copy construct.
        obj = Empty()
        obj.__class__ = self.__class__
        obj.__dict__ = self.__dict__.copy()
        return obj

    def __reduce__(self):
        """
        Pickling should return the model._meta.fields instance of the field,
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
            self.model._meta.package_label,
            self.model._meta.object_name,
            self.name,
        )

    def get_pk_value_on_save(self, instance):
        """
        Hook to generate new PK values on save. This method is called when
        saving instances with no primary key value set. If this method returns
        something else than None, then the returned value is used when saving
        the new instance.
        """
        if self.default:
            return self.get_default()
        return None

    def to_python(self, value):
        """
        Convert the input value into the expected Python data type, raising
        plain.exceptions.ValidationError if the data can't be converted.
        Return the converted value. Subclasses should override this.
        """
        return value

    @cached_property
    def error_messages(self):
        messages = {}
        for c in reversed(self.__class__.__mro__):
            messages.update(getattr(c, "default_error_messages", {}))
        messages.update(self._error_messages or {})
        return messages

    @cached_property
    def validators(self):
        """
        Some validators can't be created at field initialization time.
        This method provides a way to delay their creation until required.
        """
        return [*self.default_validators, *self._validators]

    def run_validators(self, value):
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

    def validate(self, value, model_instance):
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

    def clean(self, value, model_instance):
        """
        Convert the value's type and run validation. Validation errors
        from to_python() and validate() are propagated. Return the correct
        value if no error is raised.
        """
        value = self.to_python(value)
        self.validate(value, model_instance)
        self.run_validators(value)
        return value

    def db_type_parameters(self, connection):
        return DictWrapper(self.__dict__, connection.ops.quote_name, "qn_")

    def db_check(self, connection):
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

    def db_type(self, connection):
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

    def rel_db_type(self, connection):
        """
        Return the data type that a related field pointing to this field should
        use. For example, this method is called by ForeignKey to determine its data type.
        """
        return self.db_type(connection)

    def cast_db_type(self, connection):
        """Return the data type to use in the Cast() function."""
        db_type = connection.ops.cast_data_types.get(self.get_internal_type())
        if db_type:
            return db_type % self.db_type_parameters(connection)
        return self.db_type(connection)

    def db_parameters(self, connection):
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

    def db_type_suffix(self, connection):
        return connection.data_types_suffix.get(self.get_internal_type())

    def get_db_converters(self, connection):
        if hasattr(self, "from_db_value"):
            return [self.from_db_value]
        return []

    @property
    def db_returning(self):
        """
        Private API intended only to be used by Plain itself. Currently only
        the PostgreSQL backend supports returning multiple fields on a model.
        """
        return False

    def set_attributes_from_name(self, name):
        self.name = self.name or name
        self.attname, self.column = self.get_attname_column()
        self.concrete = self.column is not None

    def contribute_to_class(self, cls, name, private_only=False):
        """
        Register the field with the model class it belongs to.

        If private_only is True, create a separate instance of this field
        for every subclass of cls, even if cls is not an abstract model.
        """
        self.set_attributes_from_name(name)
        self.model = cls
        cls._meta.add_field(self, private=private_only)
        if self.column:
            setattr(cls, self.attname, self.descriptor_class(self))
        if self.choices is not None:
            # Don't override a get_FOO_display() method defined explicitly on
            # this class, but don't check methods derived from inheritance, to
            # allow overriding inherited choices. For more complex inheritance
            # structures users should override contribute_to_class().
            if f"get_{self.name}_display" not in cls.__dict__:
                setattr(
                    cls,
                    f"get_{self.name}_display",
                    partialmethod(cls._get_FIELD_display, field=self),
                )

    def get_attname(self):
        return self.name

    def get_attname_column(self):
        attname = self.get_attname()
        column = self.db_column or attname
        return attname, column

    def get_internal_type(self):
        return self.__class__.__name__

    def pre_save(self, model_instance, add):
        """Return field's value just before saving."""
        return getattr(model_instance, self.attname)

    def get_prep_value(self, value):
        """Perform preliminary non-db specific value checks and conversions."""
        if isinstance(value, Promise):
            value = value._proxy____cast()
        return value

    def get_db_prep_value(self, value, connection, prepared=False):
        """
        Return field's value prepared for interacting with the database backend.

        Used by the default implementations of get_db_prep_save().
        """
        if not prepared:
            value = self.get_prep_value(value)
        return value

    def get_db_prep_save(self, value, connection):
        """Return field's value prepared for saving into a database."""
        if hasattr(value, "as_sql"):
            return value
        return self.get_db_prep_value(value, connection=connection, prepared=False)

    def has_default(self):
        """Return a boolean of whether this field has a default value."""
        return self.default is not NOT_PROVIDED

    def get_default(self):
        """Return the default value for this field."""
        return self._get_default()

    @cached_property
    def _get_default(self):
        if self.has_default():
            if callable(self.default):
                return self.default
            return lambda: self.default

        if (
            not self.empty_strings_allowed
            or self.allow_null
            and not connection.features.interprets_empty_strings_as_nulls
        ):
            return return_None
        return str  # return empty string

    def get_choices(
        self,
        include_blank=True,
        blank_choice=BLANK_CHOICE_DASH,
        limit_choices_to=None,
        ordering=(),
    ):
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
            else "pk"
        )
        qs = rel_model._default_manager.complex_filter(limit_choices_to)
        if ordering:
            qs = qs.order_by(*ordering)
        return (blank_choice if include_blank else []) + [
            (choice_func(x), str(x)) for x in qs
        ]

    def value_to_string(self, obj):
        """
        Return a string value of this field from the passed obj.
        This is used by the serialization framework.
        """
        return str(self.value_from_object(obj))

    def _get_flatchoices(self):
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

    def save_form_data(self, instance, data):
        setattr(instance, self.name, data)

    def value_from_object(self, obj):
        """Return the value of this field in the given model instance."""
        return getattr(obj, self.attname)


class BooleanField(Field):
    empty_strings_allowed = False
    default_error_messages = {
        "invalid": "“%(value)s” value must be either True or False.",
        "invalid_nullable": "“%(value)s” value must be either True, False, or None.",
    }
    description = "Boolean (Either True or False)"

    def get_internal_type(self):
        return "BooleanField"

    def to_python(self, value):
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

    def get_prep_value(self, value):
        value = super().get_prep_value(value)
        if value is None:
            return None
        return self.to_python(value)


class CharField(Field):
    def __init__(self, *, db_collation=None, **kwargs):
        super().__init__(**kwargs)
        self.db_collation = db_collation
        if self.max_length is not None:
            self.validators.append(validators.MaxLengthValidator(self.max_length))

    @property
    def description(self):
        if self.max_length is not None:
            return "String (up to %(max_length)s)"
        else:
            return "String (unlimited)"

    def check(self, **kwargs):
        databases = kwargs.get("databases") or []
        return [
            *super().check(**kwargs),
            *self._check_db_collation(databases),
            *self._check_max_length_attribute(**kwargs),
        ]

    def _check_max_length_attribute(self, **kwargs):
        if self.max_length is None:
            if (
                connection.features.supports_unlimited_charfield
                or "supports_unlimited_charfield"
                in self.model._meta.required_db_features
            ):
                return []
            return [
                preflight.Error(
                    "CharFields must define a 'max_length' attribute.",
                    obj=self,
                    id="fields.E120",
                )
            ]
        elif (
            not isinstance(self.max_length, int)
            or isinstance(self.max_length, bool)
            or self.max_length <= 0
        ):
            return [
                preflight.Error(
                    "'max_length' must be a positive integer.",
                    obj=self,
                    id="fields.E121",
                )
            ]
        else:
            return []

    def _check_db_collation(self, databases):
        errors = []
        for db in databases:
            if not router.allow_migrate_model(db, self.model):
                continue
            connection = connections[db]
            if not (
                self.db_collation is None
                or "supports_collation_on_charfield"
                in self.model._meta.required_db_features
                or connection.features.supports_collation_on_charfield
            ):
                errors.append(
                    preflight.Error(
                        f"{connection.display_name} does not support a database collation on "
                        "CharFields.",
                        obj=self,
                        id="fields.E190",
                    ),
                )
        return errors

    def cast_db_type(self, connection):
        if self.max_length is None:
            return connection.ops.cast_char_field_without_max_length
        return super().cast_db_type(connection)

    def db_parameters(self, connection):
        db_params = super().db_parameters(connection)
        db_params["collation"] = self.db_collation
        return db_params

    def get_internal_type(self):
        return "CharField"

    def to_python(self, value):
        if isinstance(value, str) or value is None:
            return value
        return str(value)

    def get_prep_value(self, value):
        value = super().get_prep_value(value)
        return self.to_python(value)

    def deconstruct(self):
        name, path, args, kwargs = super().deconstruct()
        if self.db_collation:
            kwargs["db_collation"] = self.db_collation
        return name, path, args, kwargs


class CommaSeparatedIntegerField(CharField):
    default_validators = [validators.validate_comma_separated_integer_list]
    description = "Comma-separated integers"
    system_check_removed_details = {
        "msg": (
            "CommaSeparatedIntegerField is removed except for support in "
            "historical migrations."
        ),
        "hint": (
            "Use CharField(validators=[validate_comma_separated_integer_list]) instead."
        ),
        "id": "fields.E901",
    }


def _to_naive(value):
    if timezone.is_aware(value):
        value = timezone.make_naive(value, datetime.UTC)
    return value


def _get_naive_now():
    return _to_naive(timezone.now())


class DateTimeCheckMixin:
    def check(self, **kwargs):
        return [
            *super().check(**kwargs),
            *self._check_mutually_exclusive_options(),
            *self._check_fix_default_value(),
        ]

    def _check_mutually_exclusive_options(self):
        # auto_now, auto_now_add, and default are mutually exclusive
        # options. The use of more than one of these options together
        # will trigger an Error
        mutually_exclusive_options = [
            self.auto_now_add,
            self.auto_now,
            self.has_default(),
        ]
        enabled_options = [
            option not in (None, False) for option in mutually_exclusive_options
        ].count(True)
        if enabled_options > 1:
            return [
                preflight.Error(
                    "The options auto_now, auto_now_add, and default "
                    "are mutually exclusive. Only one of these options "
                    "may be present.",
                    obj=self,
                    id="fields.E160",
                )
            ]
        else:
            return []

    def _check_fix_default_value(self):
        return []

    # Concrete subclasses use this in their implementations of
    # _check_fix_default_value().
    def _check_if_value_fixed(self, value, now=None):
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
                preflight.Warning(
                    "Fixed default value provided.",
                    hint=(
                        "It seems you set a fixed date / time / datetime "
                        "value as default for this field. This may not be "
                        "what you want. If you want to have the current date "
                        "as default, use `plain.utils.timezone.now`"
                    ),
                    obj=self,
                    id="fields.W161",
                )
            ]
        return []


class DateField(DateTimeCheckMixin, Field):
    empty_strings_allowed = False
    default_error_messages = {
        "invalid": "“%(value)s” value has an invalid date format. It must be in YYYY-MM-DD format.",
        "invalid_date": "“%(value)s” value has the correct format (YYYY-MM-DD) but it is an invalid date.",
    }
    description = "Date (without time)"

    def __init__(self, *, auto_now=False, auto_now_add=False, **kwargs):
        self.auto_now, self.auto_now_add = auto_now, auto_now_add
        if auto_now or auto_now_add:
            kwargs["required"] = False
        super().__init__(**kwargs)

    def _check_fix_default_value(self):
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

    def deconstruct(self):
        name, path, args, kwargs = super().deconstruct()
        if self.auto_now:
            kwargs["auto_now"] = True
        if self.auto_now_add:
            kwargs["auto_now_add"] = True
        if self.auto_now or self.auto_now_add:
            del kwargs["required"]
        return name, path, args, kwargs

    def get_internal_type(self):
        return "DateField"

    def to_python(self, value):
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

    def pre_save(self, model_instance, add):
        if self.auto_now or (self.auto_now_add and add):
            value = datetime.date.today()
            setattr(model_instance, self.attname, value)
            return value
        else:
            return super().pre_save(model_instance, add)

    def contribute_to_class(self, cls, name, **kwargs):
        super().contribute_to_class(cls, name, **kwargs)
        if not self.allow_null:
            setattr(
                cls,
                f"get_next_by_{self.name}",
                partialmethod(
                    cls._get_next_or_previous_by_FIELD, field=self, is_next=True
                ),
            )
            setattr(
                cls,
                f"get_previous_by_{self.name}",
                partialmethod(
                    cls._get_next_or_previous_by_FIELD, field=self, is_next=False
                ),
            )

    def get_prep_value(self, value):
        value = super().get_prep_value(value)
        return self.to_python(value)

    def get_db_prep_value(self, value, connection, prepared=False):
        # Casts dates into the format expected by the backend
        if not prepared:
            value = self.get_prep_value(value)
        return connection.ops.adapt_datefield_value(value)

    def value_to_string(self, obj):
        val = self.value_from_object(obj)
        return "" if val is None else val.isoformat()


class DateTimeField(DateField):
    empty_strings_allowed = False
    default_error_messages = {
        "invalid": "“%(value)s” value has an invalid format. It must be in YYYY-MM-DD HH:MM[:ss[.uuuuuu]][TZ] format.",
        "invalid_date": "“%(value)s” value has the correct format (YYYY-MM-DD) but it is an invalid date.",
        "invalid_datetime": "“%(value)s” value has the correct format (YYYY-MM-DD HH:MM[:ss[.uuuuuu]][TZ]) but it is an invalid date/time.",
    }
    description = "Date (with time)"

    # __init__ is inherited from DateField

    def _check_fix_default_value(self):
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

    def get_internal_type(self):
        return "DateTimeField"

    def to_python(self, value):
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

    def pre_save(self, model_instance, add):
        if self.auto_now or (self.auto_now_add and add):
            value = timezone.now()
            setattr(model_instance, self.attname, value)
            return value
        else:
            return super().pre_save(model_instance, add)

    # contribute_to_class is inherited from DateField, it registers
    # get_next_by_FOO and get_prev_by_FOO

    def get_prep_value(self, value):
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

    def get_db_prep_value(self, value, connection, prepared=False):
        # Casts datetimes into the format expected by the backend
        if not prepared:
            value = self.get_prep_value(value)
        return connection.ops.adapt_datetimefield_value(value)

    def value_to_string(self, obj):
        val = self.value_from_object(obj)
        return "" if val is None else val.isoformat()


class DecimalField(Field):
    empty_strings_allowed = False
    default_error_messages = {
        "invalid": "“%(value)s” value must be a decimal number.",
    }
    description = "Decimal number"

    def __init__(
        self,
        *,
        max_digits=None,
        decimal_places=None,
        **kwargs,
    ):
        self.max_digits, self.decimal_places = max_digits, decimal_places
        super().__init__(**kwargs)

    def check(self, **kwargs):
        errors = super().check(**kwargs)

        digits_errors = [
            *self._check_decimal_places(),
            *self._check_max_digits(),
        ]
        if not digits_errors:
            errors.extend(self._check_decimal_places_and_max_digits(**kwargs))
        else:
            errors.extend(digits_errors)
        return errors

    def _check_decimal_places(self):
        try:
            decimal_places = int(self.decimal_places)
            if decimal_places < 0:
                raise ValueError()
        except TypeError:
            return [
                preflight.Error(
                    "DecimalFields must define a 'decimal_places' attribute.",
                    obj=self,
                    id="fields.E130",
                )
            ]
        except ValueError:
            return [
                preflight.Error(
                    "'decimal_places' must be a non-negative integer.",
                    obj=self,
                    id="fields.E131",
                )
            ]
        else:
            return []

    def _check_max_digits(self):
        try:
            max_digits = int(self.max_digits)
            if max_digits <= 0:
                raise ValueError()
        except TypeError:
            return [
                preflight.Error(
                    "DecimalFields must define a 'max_digits' attribute.",
                    obj=self,
                    id="fields.E132",
                )
            ]
        except ValueError:
            return [
                preflight.Error(
                    "'max_digits' must be a positive integer.",
                    obj=self,
                    id="fields.E133",
                )
            ]
        else:
            return []

    def _check_decimal_places_and_max_digits(self, **kwargs):
        if int(self.decimal_places) > int(self.max_digits):
            return [
                preflight.Error(
                    "'max_digits' must be greater or equal to 'decimal_places'.",
                    obj=self,
                    id="fields.E134",
                )
            ]
        return []

    @cached_property
    def validators(self):
        return super().validators + [
            validators.DecimalValidator(self.max_digits, self.decimal_places)
        ]

    @cached_property
    def context(self):
        return decimal.Context(prec=self.max_digits)

    def deconstruct(self):
        name, path, args, kwargs = super().deconstruct()
        if self.max_digits is not None:
            kwargs["max_digits"] = self.max_digits
        if self.decimal_places is not None:
            kwargs["decimal_places"] = self.decimal_places
        return name, path, args, kwargs

    def get_internal_type(self):
        return "DecimalField"

    def to_python(self, value):
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

    def get_db_prep_value(self, value, connection, prepared=False):
        if not prepared:
            value = self.get_prep_value(value)
        if hasattr(value, "as_sql"):
            return value
        return connection.ops.adapt_decimalfield_value(
            value, self.max_digits, self.decimal_places
        )

    def get_prep_value(self, value):
        value = super().get_prep_value(value)
        return self.to_python(value)


class DurationField(Field):
    """
    Store timedelta objects.

    Use interval on PostgreSQL, INTERVAL DAY TO SECOND on Oracle, and bigint
    of microseconds on other databases.
    """

    empty_strings_allowed = False
    default_error_messages = {
        "invalid": "“%(value)s” value has an invalid format. It must be in [DD] [[HH:]MM:]ss[.uuuuuu] format.",
    }
    description = "Duration"

    def get_internal_type(self):
        return "DurationField"

    def to_python(self, value):
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

    def get_db_prep_value(self, value, connection, prepared=False):
        if connection.features.has_native_duration_field:
            return value
        if value is None:
            return None
        return duration_microseconds(value)

    def get_db_converters(self, connection):
        converters = []
        if not connection.features.has_native_duration_field:
            converters.append(connection.ops.convert_durationfield_value)
        return converters + super().get_db_converters(connection)

    def value_to_string(self, obj):
        val = self.value_from_object(obj)
        return "" if val is None else duration_string(val)


class EmailField(CharField):
    default_validators = [validators.validate_email]
    description = "Email address"

    def __init__(self, **kwargs):
        # max_length=254 to be compliant with RFCs 3696 and 5321
        kwargs.setdefault("max_length", 254)
        super().__init__(**kwargs)

    def deconstruct(self):
        name, path, args, kwargs = super().deconstruct()
        # We do not exclude max_length if it matches default as we want to change
        # the default in future.
        return name, path, args, kwargs


class FloatField(Field):
    empty_strings_allowed = False
    default_error_messages = {
        "invalid": "“%(value)s” value must be a float.",
    }
    description = "Floating point number"

    def get_prep_value(self, value):
        value = super().get_prep_value(value)
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError) as e:
            raise e.__class__(
                f"Field '{self.name}' expected a number but got {value!r}.",
            ) from e

    def get_internal_type(self):
        return "FloatField"

    def to_python(self, value):
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


class IntegerField(Field):
    empty_strings_allowed = False
    default_error_messages = {
        "invalid": "“%(value)s” value must be an integer.",
    }
    description = "Integer"

    def check(self, **kwargs):
        return [
            *super().check(**kwargs),
            *self._check_max_length_warning(),
        ]

    def _check_max_length_warning(self):
        if self.max_length is not None:
            return [
                preflight.Warning(
                    f"'max_length' is ignored when used with {self.__class__.__name__}.",
                    hint="Remove 'max_length' from field",
                    obj=self,
                    id="fields.W122",
                )
            ]
        return []

    @cached_property
    def validators(self):
        # These validators can't be added at field initialization time since
        # they're based on values retrieved from `connection`.
        validators_ = super().validators
        internal_type = self.get_internal_type()
        min_value, max_value = connection.ops.integer_field_range(internal_type)
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

    def get_prep_value(self, value):
        value = super().get_prep_value(value)
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError) as e:
            raise e.__class__(
                f"Field '{self.name}' expected a number but got {value!r}.",
            ) from e

    def get_db_prep_value(self, value, connection, prepared=False):
        value = super().get_db_prep_value(value, connection, prepared)
        return connection.ops.adapt_integerfield_value(value, self.get_internal_type())

    def get_internal_type(self):
        return "IntegerField"

    def to_python(self, value):
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

    def get_internal_type(self):
        return "BigIntegerField"


class SmallIntegerField(IntegerField):
    description = "Small integer"

    def get_internal_type(self):
        return "SmallIntegerField"


class IPAddressField(Field):
    empty_strings_allowed = False
    description = "IPv4 address"
    system_check_removed_details = {
        "msg": (
            "IPAddressField has been removed except for support in "
            "historical migrations."
        ),
        "hint": "Use GenericIPAddressField instead.",
        "id": "fields.E900",
    }

    def __init__(self, **kwargs):
        kwargs["max_length"] = 15
        super().__init__(**kwargs)

    def deconstruct(self):
        name, path, args, kwargs = super().deconstruct()
        del kwargs["max_length"]
        return name, path, args, kwargs

    def get_prep_value(self, value):
        value = super().get_prep_value(value)
        if value is None:
            return None
        return str(value)

    def get_internal_type(self):
        return "IPAddressField"


class GenericIPAddressField(Field):
    empty_strings_allowed = False
    description = "IP address"
    default_error_messages = {}

    def __init__(
        self,
        *,
        protocol="both",
        unpack_ipv4=False,
        **kwargs,
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

    def check(self, **kwargs):
        return [
            *super().check(**kwargs),
            *self._check_required_and_null_values(**kwargs),
        ]

    def _check_required_and_null_values(self, **kwargs):
        if not getattr(self, "allow_null", False) and not getattr(
            self, "required", True
        ):
            return [
                preflight.Error(
                    "GenericIPAddressFields cannot have required=False if allow_null=False, "
                    "as blank values are stored as nulls.",
                    obj=self,
                    id="fields.E150",
                )
            ]
        return []

    def deconstruct(self):
        name, path, args, kwargs = super().deconstruct()
        if self.unpack_ipv4 is not False:
            kwargs["unpack_ipv4"] = self.unpack_ipv4
        if self.protocol != "both":
            kwargs["protocol"] = self.protocol
        if kwargs.get("max_length") == 39:
            del kwargs["max_length"]
        return name, path, args, kwargs

    def get_internal_type(self):
        return "GenericIPAddressField"

    def to_python(self, value):
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

    def get_db_prep_value(self, value, connection, prepared=False):
        if not prepared:
            value = self.get_prep_value(value)
        return connection.ops.adapt_ipaddressfield_value(value)

    def get_prep_value(self, value):
        value = super().get_prep_value(value)
        if value is None:
            return None
        if value and ":" in value:
            try:
                return clean_ipv6_address(value, self.unpack_ipv4)
            except exceptions.ValidationError:
                pass
        return str(value)


class NullBooleanField(BooleanField):
    default_error_messages = {
        "invalid": "“%(value)s” value must be either None, True or False.",
        "invalid_nullable": "“%(value)s” value must be either None, True or False.",
    }
    description = "Boolean (Either True, False or None)"
    system_check_removed_details = {
        "msg": (
            "NullBooleanField is removed except for support in historical migrations."
        ),
        "hint": "Use BooleanField(allow_null=True) instead.",
        "id": "fields.E903",
    }

    def __init__(self, **kwargs):
        kwargs["allow_null"] = True
        kwargs["required"] = False
        super().__init__(**kwargs)

    def deconstruct(self):
        name, path, args, kwargs = super().deconstruct()
        del kwargs["allow_null"]
        del kwargs["required"]
        return name, path, args, kwargs


class PositiveIntegerRelDbTypeMixin:
    def __init_subclass__(cls, **kwargs):
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

    def rel_db_type(self, connection):
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

    def get_internal_type(self):
        return "PositiveBigIntegerField"


class PositiveIntegerField(PositiveIntegerRelDbTypeMixin, IntegerField):
    description = "Positive integer"

    def get_internal_type(self):
        return "PositiveIntegerField"


class PositiveSmallIntegerField(PositiveIntegerRelDbTypeMixin, SmallIntegerField):
    description = "Positive small integer"

    def get_internal_type(self):
        return "PositiveSmallIntegerField"


class TextField(Field):
    description = "Text"

    def __init__(self, *, db_collation=None, **kwargs):
        super().__init__(**kwargs)
        self.db_collation = db_collation

    def check(self, **kwargs):
        databases = kwargs.get("databases") or []
        return [
            *super().check(**kwargs),
            *self._check_db_collation(databases),
        ]

    def _check_db_collation(self, databases):
        errors = []
        for db in databases:
            if not router.allow_migrate_model(db, self.model):
                continue
            connection = connections[db]
            if not (
                self.db_collation is None
                or "supports_collation_on_textfield"
                in self.model._meta.required_db_features
                or connection.features.supports_collation_on_textfield
            ):
                errors.append(
                    preflight.Error(
                        f"{connection.display_name} does not support a database collation on "
                        "TextFields.",
                        obj=self,
                        id="fields.E190",
                    ),
                )
        return errors

    def db_parameters(self, connection):
        db_params = super().db_parameters(connection)
        db_params["collation"] = self.db_collation
        return db_params

    def get_internal_type(self):
        return "TextField"

    def to_python(self, value):
        if isinstance(value, str) or value is None:
            return value
        return str(value)

    def get_prep_value(self, value):
        value = super().get_prep_value(value)
        return self.to_python(value)

    def deconstruct(self):
        name, path, args, kwargs = super().deconstruct()
        if self.db_collation:
            kwargs["db_collation"] = self.db_collation
        return name, path, args, kwargs


class TimeField(DateTimeCheckMixin, Field):
    empty_strings_allowed = False
    default_error_messages = {
        "invalid": "“%(value)s” value has an invalid format. It must be in HH:MM[:ss[.uuuuuu]] format.",
        "invalid_time": "“%(value)s” value has the correct format (HH:MM[:ss[.uuuuuu]]) but it is an invalid time.",
    }
    description = "Time"

    def __init__(self, *, auto_now=False, auto_now_add=False, **kwargs):
        self.auto_now, self.auto_now_add = auto_now, auto_now_add
        if auto_now or auto_now_add:
            kwargs["required"] = False
        super().__init__(**kwargs)

    def _check_fix_default_value(self):
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

    def deconstruct(self):
        name, path, args, kwargs = super().deconstruct()
        if self.auto_now is not False:
            kwargs["auto_now"] = self.auto_now
        if self.auto_now_add is not False:
            kwargs["auto_now_add"] = self.auto_now_add
        if self.auto_now or self.auto_now_add:
            del kwargs["required"]
        return name, path, args, kwargs

    def get_internal_type(self):
        return "TimeField"

    def to_python(self, value):
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

    def pre_save(self, model_instance, add):
        if self.auto_now or (self.auto_now_add and add):
            value = datetime.datetime.now().time()
            setattr(model_instance, self.attname, value)
            return value
        else:
            return super().pre_save(model_instance, add)

    def get_prep_value(self, value):
        value = super().get_prep_value(value)
        return self.to_python(value)

    def get_db_prep_value(self, value, connection, prepared=False):
        # Casts times into the format expected by the backend
        if not prepared:
            value = self.get_prep_value(value)
        return connection.ops.adapt_timefield_value(value)

    def value_to_string(self, obj):
        val = self.value_from_object(obj)
        return "" if val is None else val.isoformat()


class URLField(CharField):
    default_validators = [validators.URLValidator()]
    description = "URL"

    def __init__(self, **kwargs):
        kwargs.setdefault("max_length", 200)
        super().__init__(**kwargs)

    def deconstruct(self):
        name, path, args, kwargs = super().deconstruct()
        if kwargs.get("max_length") == 200:
            del kwargs["max_length"]
        return name, path, args, kwargs


class BinaryField(Field):
    description = "Raw binary data"
    empty_values = [None, b""]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        if self.max_length is not None:
            self.validators.append(validators.MaxLengthValidator(self.max_length))

    def check(self, **kwargs):
        return [*super().check(**kwargs), *self._check_str_default_value()]

    def _check_str_default_value(self):
        if self.has_default() and isinstance(self.default, str):
            return [
                preflight.Error(
                    "BinaryField's default cannot be a string. Use bytes "
                    "content instead.",
                    obj=self,
                    id="fields.E170",
                )
            ]
        return []

    def get_internal_type(self):
        return "BinaryField"

    def get_placeholder(self, value, compiler, connection):
        return connection.ops.binary_placeholder_sql(value)

    def get_default(self):
        if self.has_default() and not callable(self.default):
            return self.default
        default = super().get_default()
        if default == "":
            return b""
        return default

    def get_db_prep_value(self, value, connection, prepared=False):
        value = super().get_db_prep_value(value, connection, prepared)
        if value is not None:
            return connection.Database.Binary(value)
        return value

    def value_to_string(self, obj):
        """Binary data is serialized as base64"""
        return b64encode(self.value_from_object(obj)).decode("ascii")

    def to_python(self, value):
        # If it's a string, it should be base64-encoded data
        if isinstance(value, str):
            return memoryview(b64decode(value.encode("ascii")))
        return value


class UUIDField(Field):
    default_error_messages = {
        "invalid": "“%(value)s” is not a valid UUID.",
    }
    description = "Universally unique identifier"
    empty_strings_allowed = False

    def __init__(self, **kwargs):
        kwargs["max_length"] = 32
        super().__init__(**kwargs)

    def deconstruct(self):
        name, path, args, kwargs = super().deconstruct()
        del kwargs["max_length"]
        return name, path, args, kwargs

    def get_internal_type(self):
        return "UUIDField"

    def get_prep_value(self, value):
        value = super().get_prep_value(value)
        return self.to_python(value)

    def get_db_prep_value(self, value, connection, prepared=False):
        if value is None:
            return None
        if not isinstance(value, uuid.UUID):
            value = self.to_python(value)

        if connection.features.has_native_uuid_field:
            return value
        return value.hex

    def to_python(self, value):
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


class AutoFieldMixin:
    db_returning = True

    def __init__(self, *args, **kwargs):
        kwargs["required"] = False
        super().__init__(*args, **kwargs)

    def check(self, **kwargs):
        return [
            *super().check(**kwargs),
            *self._check_primary_key(),
        ]

    def _check_primary_key(self):
        if not self.primary_key:
            return [
                preflight.Error(
                    "AutoFields must set primary_key=True.",
                    obj=self,
                    id="fields.E100",
                ),
            ]
        else:
            return []

    def deconstruct(self):
        name, path, args, kwargs = super().deconstruct()
        del kwargs["required"]
        kwargs["primary_key"] = True
        return name, path, args, kwargs

    def validate(self, value, model_instance):
        pass

    def get_db_prep_value(self, value, connection, prepared=False):
        if not prepared:
            value = self.get_prep_value(value)
            value = connection.ops.validate_autopk_value(value)
        return value

    def contribute_to_class(self, cls, name, **kwargs):
        if cls._meta.auto_field:
            raise ValueError(
                f"Model {cls._meta.label} can't have more than one auto-generated field."
            )
        super().contribute_to_class(cls, name, **kwargs)
        cls._meta.auto_field = self


class AutoFieldMeta(type):
    """
    Metaclass to maintain backward inheritance compatibility for AutoField.

    It is intended that AutoFieldMixin become public API when it is possible to
    create a non-integer automatically-generated field using column defaults
    stored in the database.

    In many areas Plain also relies on using isinstance() to check for an
    automatically-generated field as a subclass of AutoField. A new flag needs
    to be implemented on Field to be used instead.

    When these issues have been addressed, this metaclass could be used to
    deprecate inheritance from AutoField and use of isinstance() with AutoField
    for detecting automatically-generated fields.
    """

    @property
    def _subclasses(self):
        return (BigAutoField, SmallAutoField)

    def __instancecheck__(self, instance):
        return isinstance(instance, self._subclasses) or super().__instancecheck__(
            instance
        )

    def __subclasscheck__(self, subclass):
        return issubclass(subclass, self._subclasses) or super().__subclasscheck__(
            subclass
        )


class AutoField(AutoFieldMixin, IntegerField, metaclass=AutoFieldMeta):
    def get_internal_type(self):
        return "AutoField"

    def rel_db_type(self, connection):
        return IntegerField().db_type(connection=connection)


class BigAutoField(AutoFieldMixin, BigIntegerField):
    def get_internal_type(self):
        return "BigAutoField"

    def rel_db_type(self, connection):
        return BigIntegerField().db_type(connection=connection)


class SmallAutoField(AutoFieldMixin, SmallIntegerField):
    def get_internal_type(self):
        return "SmallAutoField"

    def rel_db_type(self, connection):
        return SmallIntegerField().db_type(connection=connection)
