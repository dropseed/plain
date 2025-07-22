from functools import cached_property, partial

from plain import exceptions, preflight
from plain.models.constants import LOOKUP_SEP
from plain.models.deletion import SET_DEFAULT, SET_NULL
from plain.models.query_utils import PathInfo, Q
from plain.models.utils import make_model_tuple
from plain.runtime import SettingsReference

from ..registry import models_registry
from . import Field
from .mixins import FieldCacheMixin
from .related_descriptors import (
    ForeignKeyDeferredAttribute,
    ForwardManyToOneDescriptor,
    ManyToManyDescriptor,
    ReverseManyToOneDescriptor,
)
from .related_lookups import (
    RelatedExact,
    RelatedGreaterThan,
    RelatedGreaterThanOrEqual,
    RelatedIn,
    RelatedIsNull,
    RelatedLessThan,
    RelatedLessThanOrEqual,
)
from .reverse_related import ManyToManyRel, ManyToOneRel

RECURSIVE_RELATIONSHIP_CONSTANT = "self"


def resolve_relation(scope_model, relation):
    """
    Transform relation into a model or fully-qualified model string of the form
    "package_label.ModelName", relative to scope_model.

    The relation argument can be:
      * RECURSIVE_RELATIONSHIP_CONSTANT, i.e. the string "self", in which case
        the model argument will be returned.
      * A bare model name without an package_label, in which case scope_model's
        package_label will be prepended.
      * An "package_label.ModelName" string.
      * A model class, which will be returned unchanged.
    """
    # Check for recursive relations
    if relation == RECURSIVE_RELATIONSHIP_CONSTANT:
        relation = scope_model

    # Look for an "app.Model" relation
    if isinstance(relation, str):
        if "." not in relation:
            relation = f"{scope_model._meta.package_label}.{relation}"

    return relation


def lazy_related_operation(function, model, *related_models, **kwargs):
    """
    Schedule `function` to be called once `model` and all `related_models`
    have been imported and registered with the app registry. `function` will
    be called with the newly-loaded model classes as its positional arguments,
    plus any optional keyword arguments.

    The `model` argument must be a model class. Each subsequent positional
    argument is another model, or a reference to another model - see
    `resolve_relation()` for the various forms these may take. Any relative
    references will be resolved relative to `model`.

    This is a convenience wrapper for `Packages.lazy_model_operation` - the app
    registry model used is the one found in `model._meta.models_registry`.
    """
    models = [model] + [resolve_relation(model, rel) for rel in related_models]
    model_keys = (make_model_tuple(m) for m in models)
    models_registry = model._meta.models_registry
    return models_registry.lazy_model_operation(
        partial(function, **kwargs), *model_keys
    )


class RelatedField(FieldCacheMixin, Field):
    """Base class that all relational fields inherit from."""

    # Field flags
    one_to_many = False
    many_to_many = False
    many_to_one = False

    def __init__(
        self,
        *,
        related_name=None,
        related_query_name=None,
        limit_choices_to=None,
        **kwargs,
    ):
        self._related_name = related_name
        self._related_query_name = related_query_name
        self._limit_choices_to = limit_choices_to
        super().__init__(**kwargs)

    @cached_property
    def related_model(self):
        # Can't cache this property until all the models are loaded.
        models_registry.check_ready()
        return self.remote_field.model

    def check(self, **kwargs):
        return [
            *super().check(**kwargs),
            *self._check_related_name_is_valid(),
            *self._check_related_query_name_is_valid(),
            *self._check_relation_model_exists(),
            *self._check_clashes(),
        ]

    def _check_related_name_is_valid(self):
        import keyword

        related_name = self.remote_field.related_name
        if related_name is None:
            return []
        is_valid_id = (
            not keyword.iskeyword(related_name) and related_name.isidentifier()
        )
        if not (is_valid_id or related_name.endswith("+")):
            return [
                preflight.Error(
                    f"The name '{self.remote_field.related_name}' is invalid related_name for field {self.model._meta.object_name}.{self.name}",
                    hint=(
                        "Related name must be a valid Python identifier or end with a "
                        "'+'"
                    ),
                    obj=self,
                    id="fields.E306",
                )
            ]
        return []

    def _check_related_query_name_is_valid(self):
        if self.remote_field.is_hidden():
            return []
        rel_query_name = self.related_query_name()
        errors = []
        if rel_query_name.endswith("_"):
            errors.append(
                preflight.Error(
                    f"Reverse query name '{rel_query_name}' must not end with an underscore.",
                    hint=(
                        "Add or change a related_name or related_query_name "
                        "argument for this field."
                    ),
                    obj=self,
                    id="fields.E308",
                )
            )
        if LOOKUP_SEP in rel_query_name:
            errors.append(
                preflight.Error(
                    f"Reverse query name '{rel_query_name}' must not contain '{LOOKUP_SEP}'.",
                    hint=(
                        "Add or change a related_name or related_query_name "
                        "argument for this field."
                    ),
                    obj=self,
                    id="fields.E309",
                )
            )
        return errors

    def _check_relation_model_exists(self):
        rel_is_missing = (
            self.remote_field.model not in self.opts.models_registry.get_models()
        )
        rel_is_string = isinstance(self.remote_field.model, str)
        model_name = (
            self.remote_field.model
            if rel_is_string
            else self.remote_field.model._meta.object_name
        )
        if rel_is_missing and rel_is_string:
            return [
                preflight.Error(
                    f"Field defines a relation with model '{model_name}', which is either "
                    "not installed, or is abstract.",
                    obj=self,
                    id="fields.E300",
                )
            ]
        return []

    def _check_clashes(self):
        """Check accessor and reverse query name clashes."""
        from plain.models.base import ModelBase

        errors = []
        opts = self.model._meta

        # f.remote_field.model may be a string instead of a model. Skip if
        # model name is not resolved.
        if not isinstance(self.remote_field.model, ModelBase):
            return []

        # Consider that we are checking field `Model.foreign` and the models
        # are:
        #
        #     class Target(models.Model):
        #         model = models.IntegerField()
        #         model_set = models.IntegerField()
        #
        #     class Model(models.Model):
        #         foreign = models.ForeignKey(Target)
        #         m2m = models.ManyToManyField(Target)

        # rel_opts.object_name == "Target"
        rel_opts = self.remote_field.model._meta
        # If the field doesn't install a backward relation on the target model
        # (so `is_hidden` returns True), then there are no clashes to check
        # and we can skip these fields.
        rel_is_hidden = self.remote_field.is_hidden()
        rel_name = self.remote_field.get_accessor_name()  # i. e. "model_set"
        rel_query_name = self.related_query_name()  # i. e. "model"
        # i.e. "package_label.Model.field".
        field_name = f"{opts.label}.{self.name}"

        # Check clashes between accessor or reverse query name of `field`
        # and any other field name -- i.e. accessor for Model.foreign is
        # model_set and it clashes with Target.model_set.
        potential_clashes = rel_opts.fields + rel_opts.many_to_many
        for clash_field in potential_clashes:
            # i.e. "package_label.Target.model_set".
            clash_name = f"{rel_opts.label}.{clash_field.name}"
            if not rel_is_hidden and clash_field.name == rel_name:
                errors.append(
                    preflight.Error(
                        f"Reverse accessor '{rel_opts.object_name}.{rel_name}' "
                        f"for '{field_name}' clashes with field name "
                        f"'{clash_name}'.",
                        hint=(
                            f"Rename field '{clash_name}', or add/change a related_name "
                            f"argument to the definition for field '{field_name}'."
                        ),
                        obj=self,
                        id="fields.E302",
                    )
                )

            if clash_field.name == rel_query_name:
                errors.append(
                    preflight.Error(
                        f"Reverse query name for '{field_name}' clashes with field name '{clash_name}'.",
                        hint=(
                            f"Rename field '{clash_name}', or add/change a related_name "
                            f"argument to the definition for field '{field_name}'."
                        ),
                        obj=self,
                        id="fields.E303",
                    )
                )

        # Check clashes between accessors/reverse query names of `field` and
        # any other field accessor -- i. e. Model.foreign accessor clashes with
        # Model.m2m accessor.
        potential_clashes = (r for r in rel_opts.related_objects if r.field is not self)
        for clash_field in potential_clashes:
            # i.e. "package_label.Model.m2m".
            clash_name = (
                f"{clash_field.related_model._meta.label}.{clash_field.field.name}"
            )
            if not rel_is_hidden and clash_field.get_accessor_name() == rel_name:
                errors.append(
                    preflight.Error(
                        f"Reverse accessor '{rel_opts.object_name}.{rel_name}' "
                        f"for '{field_name}' clashes with reverse accessor for "
                        f"'{clash_name}'.",
                        hint=(
                            "Add or change a related_name argument "
                            f"to the definition for '{field_name}' or '{clash_name}'."
                        ),
                        obj=self,
                        id="fields.E304",
                    )
                )

            if clash_field.get_accessor_name() == rel_query_name:
                errors.append(
                    preflight.Error(
                        f"Reverse query name for '{field_name}' clashes with reverse query name "
                        f"for '{clash_name}'.",
                        hint=(
                            "Add or change a related_name argument "
                            f"to the definition for '{field_name}' or '{clash_name}'."
                        ),
                        obj=self,
                        id="fields.E305",
                    )
                )

        return errors

    def db_type(self, connection):
        # By default related field will not have a column as it relates to
        # columns from another table.
        return None

    def contribute_to_class(self, cls, name, private_only=False, **kwargs):
        super().contribute_to_class(cls, name, private_only=private_only, **kwargs)

        self.opts = cls._meta

        if self.remote_field.related_name:
            related_name = self.remote_field.related_name
        else:
            related_name = self.opts.default_related_name
        if related_name:
            related_name %= {
                "class": cls.__name__.lower(),
                "model_name": cls._meta.model_name.lower(),
                "package_label": cls._meta.package_label.lower(),
            }
            self.remote_field.related_name = related_name

        if self.remote_field.related_query_name:
            related_query_name = self.remote_field.related_query_name % {
                "class": cls.__name__.lower(),
                "package_label": cls._meta.package_label.lower(),
            }
            self.remote_field.related_query_name = related_query_name

        def resolve_related_class(model, related, field):
            field.remote_field.model = related
            field.do_related_class(related, model)

        lazy_related_operation(
            resolve_related_class, cls, self.remote_field.model, field=self
        )

    def deconstruct(self):
        name, path, args, kwargs = super().deconstruct()
        if self._limit_choices_to:
            kwargs["limit_choices_to"] = self._limit_choices_to
        if self._related_name is not None:
            kwargs["related_name"] = self._related_name
        if self._related_query_name is not None:
            kwargs["related_query_name"] = self._related_query_name
        return name, path, args, kwargs

    def get_forward_related_filter(self, obj):
        """
        Return the keyword arguments that when supplied to
        self.model.object.filter(), would select all instances related through
        this field to the remote obj. This is used to build the querysets
        returned by related descriptors. obj is an instance of
        self.related_field.model.
        """
        return {
            f"{self.name}__{rh_field.name}": getattr(obj, rh_field.attname)
            for _, rh_field in self.related_fields
        }

    def get_reverse_related_filter(self, obj):
        """
        Complement to get_forward_related_filter(). Return the keyword
        arguments that when passed to self.related_field.model.object.filter()
        select all instances of self.related_field.model related through
        this field to obj. obj is an instance of self.model.
        """
        return Q.create(
            [
                (rh_field.attname, getattr(obj, lh_field.attname))
                for lh_field, rh_field in self.related_fields
            ]
        )

    def set_attributes_from_rel(self):
        self.name = self.name or (self.remote_field.model._meta.model_name + "_" + "id")
        self.remote_field.set_field_name()

    def do_related_class(self, other, cls):
        self.set_attributes_from_rel()
        self.contribute_to_related_class(other, self.remote_field)

    def get_limit_choices_to(self):
        """
        Return ``limit_choices_to`` for this model field.

        If it is a callable, it will be invoked and the result will be
        returned.
        """
        if callable(self.remote_field.limit_choices_to):
            return self.remote_field.limit_choices_to()
        return self.remote_field.limit_choices_to

    def related_query_name(self):
        """
        Define the name that can be used to identify this related object in a
        table-spanning query.
        """
        return (
            self.remote_field.related_query_name
            or self.remote_field.related_name
            or self.opts.model_name
        )

    @property
    def target_field(self):
        """
        When filtering against this relation, return the field on the remote
        model against which the filtering should happen.
        """
        target_fields = self.path_infos[-1].target_fields
        if len(target_fields) > 1:
            raise exceptions.FieldError(
                "The relation has multiple target fields, but only single target field "
                "was asked for"
            )
        return target_fields[0]

    def get_cache_name(self):
        return self.name


class ForeignKey(RelatedField):
    """
    Provide a many-to-one relation by adding a column to the local model
    to hold the remote value.

    ForeignKey targets the primary key (id) of the remote model.
    """

    descriptor_class = ForeignKeyDeferredAttribute
    related_accessor_class = ReverseManyToOneDescriptor
    forward_related_accessor_class = ForwardManyToOneDescriptor
    rel_class = ManyToOneRel

    # Field flags - ForeignKey is many-to-one
    many_to_one = True

    empty_strings_allowed = False
    default_error_messages = {
        "invalid": "%(model)s instance with %(field)s %(value)r does not exist."
    }
    description = "Foreign Key (type determined by related field)"

    def __init__(
        self,
        to,
        on_delete,
        related_name=None,
        related_query_name=None,
        limit_choices_to=None,
        db_index=True,
        db_constraint=True,
        **kwargs,
    ):
        try:
            to._meta.model_name
        except AttributeError:
            if not isinstance(to, str):
                raise TypeError(
                    f"{self.__class__.__name__}({to!r}) is invalid. First parameter to ForeignKey must be "
                    f"either a model, a model name, or the string {RECURSIVE_RELATIONSHIP_CONSTANT!r}"
                )
        if not callable(on_delete):
            raise TypeError("on_delete must be callable.")

        rel = self.rel_class(
            self,
            to,
            related_name=related_name,
            related_query_name=related_query_name,
            limit_choices_to=limit_choices_to,
            on_delete=on_delete,
        )

        super().__init__(
            rel=rel,
            related_name=related_name,
            related_query_name=related_query_name,
            limit_choices_to=limit_choices_to,
            **kwargs,
        )
        self.db_index = db_index
        self.db_constraint = db_constraint

    def __copy__(self):
        obj = super().__copy__()
        # Remove any cached PathInfo values.
        obj.__dict__.pop("path_infos", None)
        obj.__dict__.pop("reverse_path_infos", None)
        return obj

    @cached_property
    def related_fields(self):
        return self.resolve_related_fields()

    @cached_property
    def reverse_related_fields(self):
        return [(rhs_field, lhs_field) for lhs_field, rhs_field in self.related_fields]

    @cached_property
    def local_related_fields(self):
        return tuple(lhs_field for lhs_field, rhs_field in self.related_fields)

    @cached_property
    def foreign_related_fields(self):
        return tuple(
            rhs_field for lhs_field, rhs_field in self.related_fields if rhs_field
        )

    def get_local_related_value(self, instance):
        # Always returns the value of the single local field
        field = self.local_related_fields[0]
        if field.primary_key:
            return (instance.id,)
        return (getattr(instance, field.attname),)

    def get_foreign_related_value(self, instance):
        # Always returns the id of the foreign instance
        return (instance.id,)

    def get_joining_columns(self, reverse_join=False):
        # Always returns a single column pair
        if reverse_join:
            from_field, to_field = self.related_fields[0]
            return ((to_field.column, from_field.column),)
        else:
            from_field, to_field = self.related_fields[0]
            return ((from_field.column, to_field.column),)

    def get_reverse_joining_columns(self):
        return self.get_joining_columns(reverse_join=True)

    def get_extra_restriction(self, alias, related_alias):
        """
        Return a pair condition used for joining and subquery pushdown. The
        condition is something that responds to as_sql(compiler, connection)
        method.

        Note that currently referring both the 'alias' and 'related_alias'
        will not work in some conditions, like subquery pushdown.

        A parallel method is get_extra_descriptor_filter() which is used in
        instance.fieldname related object fetching.
        """
        return None

    def get_path_info(self, filtered_relation=None):
        """Get path from this field to the related model."""
        opts = self.remote_field.model._meta
        from_opts = self.model._meta
        return [
            PathInfo(
                from_opts=from_opts,
                to_opts=opts,
                target_fields=self.foreign_related_fields,
                join_field=self,
                m2m=False,
                direct=True,
                filtered_relation=filtered_relation,
            )
        ]

    @cached_property
    def path_infos(self):
        return self.get_path_info()

    def get_reverse_path_info(self, filtered_relation=None):
        """Get path from the related model to this field's model."""
        opts = self.model._meta
        from_opts = self.remote_field.model._meta
        return [
            PathInfo(
                from_opts=from_opts,
                to_opts=opts,
                target_fields=(opts.get_field("id"),),
                join_field=self.remote_field,
                m2m=not self.primary_key,
                direct=False,
                filtered_relation=filtered_relation,
            )
        ]

    @cached_property
    def reverse_path_infos(self):
        return self.get_reverse_path_info()

    def contribute_to_class(self, cls, name, private_only=False, **kwargs):
        super().contribute_to_class(cls, name, private_only=private_only, **kwargs)
        setattr(cls, self.name, self.forward_related_accessor_class(self))

    def contribute_to_related_class(self, cls, related):
        # Internal FK's - i.e., those with a related name ending with '+'
        if not self.remote_field.is_hidden():
            setattr(
                cls._meta.concrete_model,
                related.get_accessor_name(),
                self.related_accessor_class(related),
            )
            # While 'limit_choices_to' might be a callable, simply pass
            # it along for later - this is too early because it's still
            # model load time.
            if self.remote_field.limit_choices_to:
                cls._meta.related_fkey_lookups.append(
                    self.remote_field.limit_choices_to
                )

    def check(self, **kwargs):
        return [
            *super().check(**kwargs),
            *self._check_on_delete(),
        ]

    def _check_on_delete(self):
        on_delete = getattr(self.remote_field, "on_delete", None)
        if on_delete == SET_NULL and not self.allow_null:
            return [
                preflight.Error(
                    "Field specifies on_delete=SET_NULL, but cannot be null.",
                    hint=(
                        "Set allow_null=True argument on the field, or change the on_delete "
                        "rule."
                    ),
                    obj=self,
                    id="fields.E320",
                )
            ]
        elif on_delete == SET_DEFAULT and not self.has_default():
            return [
                preflight.Error(
                    "Field specifies on_delete=SET_DEFAULT, but has no default value.",
                    hint="Set a default value, or change the on_delete rule.",
                    obj=self,
                    id="fields.E321",
                )
            ]
        else:
            return []

    def deconstruct(self):
        name, path, args, kwargs = super().deconstruct()
        kwargs["on_delete"] = self.remote_field.on_delete

        if isinstance(self.remote_field.model, SettingsReference):
            kwargs["to"] = self.remote_field.model
        elif isinstance(self.remote_field.model, str):
            if "." in self.remote_field.model:
                package_label, model_name = self.remote_field.model.split(".")
                kwargs["to"] = f"{package_label}.{model_name.lower()}"
            else:
                kwargs["to"] = self.remote_field.model.lower()
        else:
            kwargs["to"] = self.remote_field.model._meta.label_lower

        if self.db_index is not True:
            kwargs["db_index"] = self.db_index

        if self.db_constraint is not True:
            kwargs["db_constraint"] = self.db_constraint

        return name, path, args, kwargs

    def to_python(self, value):
        return self.target_field.to_python(value)

    @property
    def target_field(self):
        return self.foreign_related_fields[0]

    def validate(self, value, model_instance):
        super().validate(value, model_instance)
        if value is None:
            return

        qs = self.remote_field.model._base_manager.filter(
            **{self.remote_field.field_name: value}
        )
        qs = qs.complex_filter(self.get_limit_choices_to())
        if not qs.exists():
            raise exceptions.ValidationError(
                self.error_messages["invalid"],
                code="invalid",
                params={
                    "model": self.remote_field.model._meta.model_name,
                    "id": value,
                    "field": self.remote_field.field_name,
                    "value": value,
                },
            )

    def resolve_related_fields(self):
        if isinstance(self.remote_field.model, str):
            raise ValueError(
                f"Related model {self.remote_field.model!r} cannot be resolved"
            )
        from_field = self
        to_field = self.remote_field.model._meta.get_field("id")
        related_fields = [(from_field, to_field)]

        for from_field, to_field in related_fields:
            if (
                to_field
                and to_field.model != self.remote_field.model._meta.concrete_model
            ):
                raise exceptions.FieldError(
                    f"'{self.model._meta.label}.{self.name}' refers to field '{to_field.name}' which is not local to model "
                    f"'{self.remote_field.model._meta.concrete_model._meta.label}'."
                )
        return related_fields

    def get_attname(self):
        return f"{self.name}_id"

    def get_attname_column(self):
        attname = self.get_attname()
        column = self.db_column or attname
        return attname, column

    def get_default(self):
        """Return the to_field if the default value is an object."""
        field_default = super().get_default()
        if isinstance(field_default, self.remote_field.model):
            return getattr(field_default, self.target_field.attname)
        return field_default

    def get_db_prep_save(self, value, connection):
        if value is None or (
            value == "" and not self.target_field.empty_strings_allowed
        ):
            return None
        else:
            return self.target_field.get_db_prep_save(value, connection=connection)

    def get_db_prep_value(self, value, connection, prepared=False):
        return self.target_field.get_db_prep_value(value, connection, prepared)

    def get_prep_value(self, value):
        return self.target_field.get_prep_value(value)

    def db_check(self, connection):
        return None

    def db_type(self, connection):
        return self.target_field.rel_db_type(connection=connection)

    def cast_db_type(self, connection):
        return self.target_field.cast_db_type(connection=connection)

    def db_parameters(self, connection):
        target_db_parameters = self.target_field.db_parameters(connection)
        return {
            "type": self.db_type(connection),
            "check": self.db_check(connection),
            "collation": target_db_parameters.get("collation"),
        }

    def get_col(self, alias, output_field=None):
        if output_field is None:
            output_field = self.target_field
            while isinstance(output_field, ForeignKey):
                output_field = output_field.target_field
                if output_field is self:
                    raise ValueError("Cannot resolve output_field.")
        return super().get_col(alias, output_field)


# Register lookups for ForeignKey
ForeignKey.register_lookup(RelatedIn)
ForeignKey.register_lookup(RelatedExact)
ForeignKey.register_lookup(RelatedLessThan)
ForeignKey.register_lookup(RelatedGreaterThan)
ForeignKey.register_lookup(RelatedGreaterThanOrEqual)
ForeignKey.register_lookup(RelatedLessThanOrEqual)
ForeignKey.register_lookup(RelatedIsNull)


class ManyToManyField(RelatedField):
    """
    Provide a many-to-many relation by using an intermediary model that
    holds two ForeignKey fields pointed at the two sides of the relation.

    Unless a ``through`` model was provided, ManyToManyField will use the
    create_many_to_many_intermediary_model factory to automatically generate
    the intermediary model.
    """

    # Field flags
    many_to_many = True
    many_to_one = False
    one_to_many = False

    rel_class = ManyToManyRel

    description = "Many-to-many relationship"

    def __init__(
        self,
        to,
        *,
        through,
        through_fields=None,
        related_name=None,
        related_query_name=None,
        limit_choices_to=None,
        symmetrical=None,
        **kwargs,
    ):
        try:
            to._meta
        except AttributeError:
            if not isinstance(to, str):
                raise TypeError(
                    f"{self.__class__.__name__}({to!r}) is invalid. First parameter to ManyToManyField "
                    f"must be either a model, a model name, or the string {RECURSIVE_RELATIONSHIP_CONSTANT!r}"
                )

        if symmetrical is None:
            symmetrical = to == RECURSIVE_RELATIONSHIP_CONSTANT

        if not through:
            raise ValueError("ManyToManyField must have a 'through' argument.")

        kwargs["rel"] = self.rel_class(
            self,
            to,
            related_name=related_name,
            related_query_name=related_query_name,
            limit_choices_to=limit_choices_to,
            symmetrical=symmetrical,
            through=through,
            through_fields=through_fields,
        )
        self.has_null_arg = "allow_null" in kwargs

        super().__init__(
            related_name=related_name,
            related_query_name=related_query_name,
            limit_choices_to=limit_choices_to,
            **kwargs,
        )

    def check(self, **kwargs):
        return [
            *super().check(**kwargs),
            *self._check_relationship_model(**kwargs),
            *self._check_ignored_options(**kwargs),
            *self._check_table_uniqueness(**kwargs),
        ]

    def _check_ignored_options(self, **kwargs):
        warnings = []

        if self.has_null_arg:
            warnings.append(
                preflight.Warning(
                    "null has no effect on ManyToManyField.",
                    obj=self,
                    id="fields.W340",
                )
            )

        if self._validators:
            warnings.append(
                preflight.Warning(
                    "ManyToManyField does not support validators.",
                    obj=self,
                    id="fields.W341",
                )
            )
        if self.remote_field.symmetrical and self._related_name:
            warnings.append(
                preflight.Warning(
                    "related_name has no effect on ManyToManyField "
                    'with a symmetrical relationship, e.g. to "self".',
                    obj=self,
                    id="fields.W345",
                )
            )
        if self.db_comment:
            warnings.append(
                preflight.Warning(
                    "db_comment has no effect on ManyToManyField.",
                    obj=self,
                    id="fields.W346",
                )
            )

        return warnings

    def _check_relationship_model(self, from_model=None, **kwargs):
        if hasattr(self.remote_field.through, "_meta"):
            qualified_model_name = f"{self.remote_field.through._meta.package_label}.{self.remote_field.through.__name__}"
        else:
            qualified_model_name = self.remote_field.through

        errors = []

        if self.remote_field.through not in self.opts.models_registry.get_models():
            # The relationship model is not installed.
            errors.append(
                preflight.Error(
                    "Field specifies a many-to-many relation through model "
                    f"'{qualified_model_name}', which has not been installed.",
                    obj=self,
                    id="fields.E331",
                )
            )

        else:
            assert from_model is not None, (
                "ManyToManyField with intermediate "
                "tables cannot be checked if you don't pass the model "
                "where the field is attached to."
            )
            # Set some useful local variables
            to_model = resolve_relation(from_model, self.remote_field.model)
            from_model_name = from_model._meta.object_name
            if isinstance(to_model, str):
                to_model_name = to_model
            else:
                to_model_name = to_model._meta.object_name
            relationship_model_name = self.remote_field.through._meta.object_name
            self_referential = from_model == to_model
            # Count foreign keys in intermediate model
            if self_referential:
                seen_self = sum(
                    from_model == getattr(field.remote_field, "model", None)
                    for field in self.remote_field.through._meta.fields
                )

                if seen_self > 2 and not self.remote_field.through_fields:
                    errors.append(
                        preflight.Error(
                            "The model is used as an intermediate model by "
                            f"'{self}', but it has more than two foreign keys "
                            f"to '{from_model_name}', which is ambiguous. You must specify "
                            "which two foreign keys Plain should use via the "
                            "through_fields keyword argument.",
                            hint=(
                                "Use through_fields to specify which two foreign keys "
                                "Plain should use."
                            ),
                            obj=self.remote_field.through,
                            id="fields.E333",
                        )
                    )

            else:
                # Count foreign keys in relationship model
                seen_from = sum(
                    from_model == getattr(field.remote_field, "model", None)
                    for field in self.remote_field.through._meta.fields
                )
                seen_to = sum(
                    to_model == getattr(field.remote_field, "model", None)
                    for field in self.remote_field.through._meta.fields
                )

                if seen_from > 1 and not self.remote_field.through_fields:
                    errors.append(
                        preflight.Error(
                            (
                                "The model is used as an intermediate model by "
                                f"'{self}', but it has more than one foreign key "
                                f"from '{from_model_name}', which is ambiguous. You must specify "
                                "which foreign key Plain should use via the "
                                "through_fields keyword argument."
                            ),
                            hint=(
                                "If you want to create a recursive relationship, "
                                f'use ManyToManyField("{RECURSIVE_RELATIONSHIP_CONSTANT}", through="{relationship_model_name}").'
                            ),
                            obj=self,
                            id="fields.E334",
                        )
                    )

                if seen_to > 1 and not self.remote_field.through_fields:
                    errors.append(
                        preflight.Error(
                            "The model is used as an intermediate model by "
                            f"'{self}', but it has more than one foreign key "
                            f"to '{to_model_name}', which is ambiguous. You must specify "
                            "which foreign key Plain should use via the "
                            "through_fields keyword argument.",
                            hint=(
                                "If you want to create a recursive relationship, "
                                f'use ManyToManyField("{RECURSIVE_RELATIONSHIP_CONSTANT}", through="{relationship_model_name}").'
                            ),
                            obj=self,
                            id="fields.E335",
                        )
                    )

                if seen_from == 0 or seen_to == 0:
                    errors.append(
                        preflight.Error(
                            "The model is used as an intermediate model by "
                            f"'{self}', but it does not have a foreign key to '{from_model_name}' or '{to_model_name}'.",
                            obj=self.remote_field.through,
                            id="fields.E336",
                        )
                    )

        # Validate `through_fields`.
        if self.remote_field.through_fields is not None:
            # Validate that we're given an iterable of at least two items
            # and that none of them is "falsy".
            if not (
                len(self.remote_field.through_fields) >= 2
                and self.remote_field.through_fields[0]
                and self.remote_field.through_fields[1]
            ):
                errors.append(
                    preflight.Error(
                        "Field specifies 'through_fields' but does not provide "
                        "the names of the two link fields that should be used "
                        f"for the relation through model '{qualified_model_name}'.",
                        hint=(
                            "Make sure you specify 'through_fields' as "
                            "through_fields=('field1', 'field2')"
                        ),
                        obj=self,
                        id="fields.E337",
                    )
                )

            # Validate the given through fields -- they should be actual
            # fields on the through model, and also be foreign keys to the
            # expected models.
            else:
                assert from_model is not None, (
                    "ManyToManyField with intermediate "
                    "tables cannot be checked if you don't pass the model "
                    "where the field is attached to."
                )

                source, through, target = (
                    from_model,
                    self.remote_field.through,
                    self.remote_field.model,
                )
                source_field_name, target_field_name = self.remote_field.through_fields[
                    :2
                ]

                for field_name, related_model in (
                    (source_field_name, source),
                    (target_field_name, target),
                ):
                    possible_field_names = []
                    for f in through._meta.fields:
                        if (
                            hasattr(f, "remote_field")
                            and getattr(f.remote_field, "model", None) == related_model
                        ):
                            possible_field_names.append(f.name)
                    if possible_field_names:
                        hint = (
                            "Did you mean one of the following foreign keys to '{}': "
                            "{}?".format(
                                related_model._meta.object_name,
                                ", ".join(possible_field_names),
                            )
                        )
                    else:
                        hint = None

                    try:
                        field = through._meta.get_field(field_name)
                    except exceptions.FieldDoesNotExist:
                        errors.append(
                            preflight.Error(
                                f"The intermediary model '{qualified_model_name}' has no field '{field_name}'.",
                                hint=hint,
                                obj=self,
                                id="fields.E338",
                            )
                        )
                    else:
                        if not (
                            hasattr(field, "remote_field")
                            and getattr(field.remote_field, "model", None)
                            == related_model
                        ):
                            errors.append(
                                preflight.Error(
                                    f"'{through._meta.object_name}.{field_name}' is not a foreign key to '{related_model._meta.object_name}'.",
                                    hint=hint,
                                    obj=self,
                                    id="fields.E339",
                                )
                            )

        return errors

    def _check_table_uniqueness(self, **kwargs):
        if isinstance(self.remote_field.through, str):
            return []
        registered_tables = {
            model._meta.db_table: model
            for model in self.opts.models_registry.get_models()
            if model != self.remote_field.through
        }
        m2m_db_table = self.m2m_db_table()
        model = registered_tables.get(m2m_db_table)
        # The second condition allows multiple m2m relations on a model if
        # some point to a through model that proxies another through model.
        if (
            model
            and model._meta.concrete_model
            != self.remote_field.through._meta.concrete_model
        ):
            clashing_obj = model._meta.label
            return [
                preflight.Error(
                    f"The field's intermediary table '{m2m_db_table}' clashes with the "
                    f"table name of '{clashing_obj}'.",
                    obj=self,
                    hint=None,
                    id="fields.E340",
                )
            ]
        return []

    def deconstruct(self):
        name, path, args, kwargs = super().deconstruct()

        if self.remote_field.db_constraint is not True:
            kwargs["db_constraint"] = self.remote_field.db_constraint

        # Lowercase model names as they should be treated as case-insensitive.
        if isinstance(self.remote_field.model, str):
            if "." in self.remote_field.model:
                package_label, model_name = self.remote_field.model.split(".")
                kwargs["to"] = f"{package_label}.{model_name.lower()}"
            else:
                kwargs["to"] = self.remote_field.model.lower()
        else:
            kwargs["to"] = self.remote_field.model._meta.label_lower

        if isinstance(self.remote_field.through, str):
            kwargs["through"] = self.remote_field.through
        else:
            kwargs["through"] = self.remote_field.through._meta.label

        return name, path, args, kwargs

    def _get_path_info(self, direct=False, filtered_relation=None):
        """Called by both direct and indirect m2m traversal."""
        int_model = self.remote_field.through
        linkfield1 = int_model._meta.get_field(self.m2m_field_name())
        linkfield2 = int_model._meta.get_field(self.m2m_reverse_field_name())
        if direct:
            join1infos = linkfield1.reverse_path_infos
            if filtered_relation:
                join2infos = linkfield2.get_path_info(filtered_relation)
            else:
                join2infos = linkfield2.path_infos
        else:
            join1infos = linkfield2.reverse_path_infos
            if filtered_relation:
                join2infos = linkfield1.get_path_info(filtered_relation)
            else:
                join2infos = linkfield1.path_infos

        return [*join1infos, *join2infos]

    def get_path_info(self, filtered_relation=None):
        return self._get_path_info(direct=True, filtered_relation=filtered_relation)

    @cached_property
    def path_infos(self):
        return self.get_path_info()

    def get_reverse_path_info(self, filtered_relation=None):
        return self._get_path_info(direct=False, filtered_relation=filtered_relation)

    @cached_property
    def reverse_path_infos(self):
        return self.get_reverse_path_info()

    def _get_m2m_db_table(self):
        """
        Function that can be curried to provide the m2m table name for this
        relation.
        """
        return self.remote_field.through._meta.db_table

    def _get_m2m_attr(self, related, attr):
        """
        Function that can be curried to provide the source accessor or DB
        column name for the m2m table.
        """
        cache_attr = f"_m2m_{attr}_cache"
        if hasattr(self, cache_attr):
            return getattr(self, cache_attr)
        if self.remote_field.through_fields is not None:
            link_field_name = self.remote_field.through_fields[0]
        else:
            link_field_name = None
        for f in self.remote_field.through._meta.fields:
            if (
                f.is_relation
                and f.remote_field.model == related.related_model
                and (link_field_name is None or link_field_name == f.name)
            ):
                setattr(self, cache_attr, getattr(f, attr))
                return getattr(self, cache_attr)

    def _get_m2m_reverse_attr(self, related, attr):
        """
        Function that can be curried to provide the related accessor or DB
        column name for the m2m table.
        """
        cache_attr = f"_m2m_reverse_{attr}_cache"
        if hasattr(self, cache_attr):
            return getattr(self, cache_attr)
        found = False
        if self.remote_field.through_fields is not None:
            link_field_name = self.remote_field.through_fields[1]
        else:
            link_field_name = None
        for f in self.remote_field.through._meta.fields:
            if f.is_relation and f.remote_field.model == related.model:
                if link_field_name is None and related.related_model == related.model:
                    # If this is an m2m-intermediate to self,
                    # the first foreign key you find will be
                    # the source column. Keep searching for
                    # the second foreign key.
                    if found:
                        setattr(self, cache_attr, getattr(f, attr))
                        break
                    else:
                        found = True
                elif link_field_name is None or link_field_name == f.name:
                    setattr(self, cache_attr, getattr(f, attr))
                    break
        return getattr(self, cache_attr)

    def contribute_to_class(self, cls, name, **kwargs):
        # To support multiple relations to self, it's useful to have a non-None
        # related name on symmetrical relations for internal reasons. The
        # concept doesn't make a lot of sense externally ("you want me to
        # specify *what* on my non-reversible relation?!"), so we set it up
        # automatically. The funky name reduces the chance of an accidental
        # clash.
        if self.remote_field.symmetrical and (
            self.remote_field.model == RECURSIVE_RELATIONSHIP_CONSTANT
            or self.remote_field.model == cls._meta.object_name
        ):
            self.remote_field.related_name = f"{name}_rel_+"
        elif self.remote_field.is_hidden():
            # If the backwards relation is disabled, replace the original
            # related_name with one generated from the m2m field name. Plain
            # still uses backwards relations internally and we need to avoid
            # clashes between multiple m2m fields with related_name == '+'.
            self.remote_field.related_name = (
                f"_{cls._meta.package_label}_{cls.__name__.lower()}_{name}_+"
            )

        super().contribute_to_class(cls, name, **kwargs)

        def resolve_through_model(_, model, field):
            field.remote_field.through = model

        lazy_related_operation(
            resolve_through_model, cls, self.remote_field.through, field=self
        )

        # Add the descriptor for the m2m relation.
        setattr(cls, self.name, ManyToManyDescriptor(self.remote_field, reverse=False))

        # Set up the accessor for the m2m table name for the relation.
        self.m2m_db_table = self._get_m2m_db_table

    def contribute_to_related_class(self, cls, related):
        # Internal M2Ms (i.e., those with a related name ending with '+')
        # don't get a related descriptor.
        if not self.remote_field.is_hidden():
            setattr(
                cls,
                related.get_accessor_name(),
                ManyToManyDescriptor(self.remote_field, reverse=True),
            )

        # Set up the accessors for the column names on the m2m table.
        self.m2m_column_name = partial(self._get_m2m_attr, related, "column")
        self.m2m_reverse_name = partial(self._get_m2m_reverse_attr, related, "column")

        self.m2m_field_name = partial(self._get_m2m_attr, related, "name")
        self.m2m_reverse_field_name = partial(
            self._get_m2m_reverse_attr, related, "name"
        )

        get_m2m_rel = partial(self._get_m2m_attr, related, "remote_field")
        self.m2m_target_field_name = lambda: get_m2m_rel().field_name
        get_m2m_reverse_rel = partial(
            self._get_m2m_reverse_attr, related, "remote_field"
        )
        self.m2m_reverse_target_field_name = lambda: get_m2m_reverse_rel().field_name

    def set_attributes_from_rel(self):
        pass

    def value_from_object(self, obj):
        return [] if obj.id is None else list(getattr(obj, self.attname).all())

    def save_form_data(self, instance, data):
        getattr(instance, self.attname).set(data)

    def db_check(self, connection):
        return None

    def db_type(self, connection):
        # A ManyToManyField is not represented by a single column,
        # so return None.
        return None

    def db_parameters(self, connection):
        return {"type": None, "check": None}
