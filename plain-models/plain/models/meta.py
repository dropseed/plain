from __future__ import annotations

import bisect
import copy
import inspect
from collections import defaultdict
from functools import cached_property
from typing import TYPE_CHECKING, Any

from plain.models.exceptions import FieldDoesNotExist
from plain.models.query import QuerySet
from plain.models.registry import models_registry as default_models_registry
from plain.utils.datastructures import ImmutableList

if TYPE_CHECKING:
    from plain.models.base import Model
    from plain.models.fields import Field

EMPTY_RELATION_TREE = ()

IMMUTABLE_WARNING = (
    "The return type of '%s' should never be mutated. If you want to manipulate this "
    "list for your own use, make a copy first."
)


def make_immutable_fields_list(name: str, data: Any) -> ImmutableList:
    return ImmutableList(data, warning=IMMUTABLE_WARNING % name)


class Meta:
    """
    Model metadata descriptor and container.

    Acts as both a descriptor (for lazy initialization and access control)
    and the actual metadata instance (cached per model class).
    """

    FORWARD_PROPERTIES = {
        "fields",
        "many_to_many",
        "concrete_fields",
        "local_concrete_fields",
        "_non_pk_concrete_field_names",
        "_forward_fields_map",
        "base_queryset",
    }
    REVERSE_PROPERTIES = {"related_objects", "fields_map", "_relation_tree"}

    # Type annotations for attributes set in _create_and_cache
    # These exist on cached instances, not on the descriptor itself
    model: type[Model]
    models_registry: Any
    _get_fields_cache: dict[Any, Any]
    local_fields: list[Field]
    local_many_to_many: list[Field]
    related_fkey_lookups: list[Any]

    def __init__(self, models_registry: Any | None = None):
        """
        Initialize the descriptor with optional configuration.

        This is called ONCE when defining the base Model class.
        The descriptor then creates cached instances per model subclass.
        """
        self._models_registry = models_registry
        self._cache: dict[type[Model], Meta] = {}

    def __get__(self, instance: Any, owner: type[Model]) -> Meta:
        """
        Descriptor protocol - returns cached Meta instance for the model class.

        This is called when accessing Model._model_meta and returns a per-class
        cached instance created by _create_and_cache().

        Can be accessed from both class and instances:
        - MyModel._model_meta (class access)
        - my_instance._model_meta (instance access - returns class's metadata)
        """
        # Allow instance access - just return the class's metadata
        if instance is not None:
            owner = instance.__class__

        # Skip for the base Model class - return descriptor
        if owner.__name__ == "Model" and owner.__module__ == "plain.models.base":
            return self  # type: ignore

        # Return cached instance or create new one
        if owner not in self._cache:
            # Create the instance and cache it BEFORE field contribution
            # to avoid infinite recursion when fields access cls._model_meta
            return self._create_and_cache(owner)

        return self._cache[owner]

    def _create_and_cache(self, model: type[Model]) -> Meta:
        """Create Meta instance and cache it before field contribution."""
        # Create instance without calling __init__
        instance = Meta.__new__(Meta)

        # Initialize basic model-specific state
        instance.model = model
        instance.models_registry = self._models_registry or default_models_registry
        instance._get_fields_cache = {}
        instance.local_fields = []
        instance.local_many_to_many = []
        instance.related_fkey_lookups = []

        # Cache the instance BEFORE processing fields to prevent recursion
        self._cache[model] = instance

        # Now process fields - they can safely access cls._model_meta
        seen_attrs = set()
        for klass in model.__mro__:
            for attr_name in list(klass.__dict__.keys()):
                if attr_name.startswith("_") or attr_name in seen_attrs:
                    continue
                seen_attrs.add(attr_name)

                attr_value = klass.__dict__[attr_name]

                if not inspect.isclass(attr_value) and hasattr(
                    attr_value, "contribute_to_class"
                ):
                    if attr_name not in model.__dict__:
                        field = copy.deepcopy(attr_value)
                    else:
                        field = attr_value
                    field.contribute_to_class(model, attr_name)

        # Set index names now that fields are contributed
        # Trigger model_options descriptor to ensure it's initialized
        # (accessing it will cache the instance)
        for index in model.model_options.indexes:
            if not index.name:
                index.set_name_with_model(model)

        return instance

    @property
    def base_queryset(self) -> QuerySet:
        """
        The base queryset is used by Plain's internal operations like cascading
        deletes, migrations, and related object lookups. It provides access to
        all objects in the database without any filtering, ensuring Plain can
        always see the complete dataset when performing framework operations.

        Unlike user-defined querysets which may filter results (e.g. only active
        objects), the base queryset must never filter out rows to prevent
        incomplete results in related queries.
        """
        return QuerySet.from_model(self.model)

    def add_field(self, field: Field) -> None:
        # Insert the given field in the order in which it was created, using
        # the "creation_counter" attribute of the field.
        # Move many-to-many related fields from self.fields into
        # self.many_to_many.
        if field.is_relation and field.many_to_many:
            bisect.insort(self.local_many_to_many, field)
        else:
            bisect.insort(self.local_fields, field)

        # If the field being added is a relation to another known field,
        # expire the cache on this field and the forward cache on the field
        # being referenced, because there will be new relationships in the
        # cache. Otherwise, expire the cache of references *to* this field.
        # The mechanism for getting at the related model is slightly odd -
        # ideally, we'd just ask for field.related_model. However, related_model
        # is a cached property, and all the models haven't been loaded yet, so
        # we need to make sure we don't cache a string reference.
        if (
            field.is_relation
            and hasattr(field.remote_field, "model")
            and field.remote_field.model
        ):
            try:
                field.remote_field.model._model_meta._expire_cache(forward=False)
            except AttributeError:
                pass
            self._expire_cache()
        else:
            self._expire_cache(reverse=False)

    @cached_property
    def fields(self) -> ImmutableList:
        """
        Return a list of all forward fields on the model and its parents,
        excluding ManyToManyFields.

        Private API intended only to be used by Plain itself; get_fields()
        combined with filtering of field properties is the public API for
        obtaining this field list.
        """

        # For legacy reasons, the fields property should only contain forward
        # fields that are not private or with a m2m cardinality. Therefore we
        # pass these three filters as filters to the generator.
        # The third lambda is a longwinded way of checking f.related_model - we don't
        # use that property directly because related_model is a cached property,
        # and all the models may not have been loaded yet; we don't want to cache
        # the string reference to the related_model.
        def is_not_an_m2m_field(f: Any) -> bool:
            return not (f.is_relation and f.many_to_many)

        def is_not_a_generic_relation(f: Any) -> bool:
            return not (f.is_relation and f.one_to_many)

        def is_not_a_generic_foreign_key(f: Any) -> bool:
            return not (
                f.is_relation
                and f.many_to_one
                and not (hasattr(f.remote_field, "model") and f.remote_field.model)
            )

        return make_immutable_fields_list(
            "fields",
            (
                f
                for f in self._get_fields(reverse=False)
                if is_not_an_m2m_field(f)
                and is_not_a_generic_relation(f)
                and is_not_a_generic_foreign_key(f)
            ),
        )

    @cached_property
    def concrete_fields(self) -> ImmutableList:
        """
        Return a list of all concrete fields on the model and its parents.

        Private API intended only to be used by Plain itself; get_fields()
        combined with filtering of field properties is the public API for
        obtaining this field list.
        """
        return make_immutable_fields_list(
            "concrete_fields", (f for f in self.fields if f.concrete)
        )

    @cached_property
    def local_concrete_fields(self) -> ImmutableList:
        """
        Return a list of all concrete fields on the model.

        Private API intended only to be used by Plain itself; get_fields()
        combined with filtering of field properties is the public API for
        obtaining this field list.
        """
        return make_immutable_fields_list(
            "local_concrete_fields", (f for f in self.local_fields if f.concrete)
        )

    @cached_property
    def many_to_many(self) -> ImmutableList:
        """
        Return a list of all many to many fields on the model and its parents.

        Private API intended only to be used by Plain itself; get_fields()
        combined with filtering of field properties is the public API for
        obtaining this list.
        """
        return make_immutable_fields_list(
            "many_to_many",
            (
                f
                for f in self._get_fields(reverse=False)
                if f.is_relation and f.many_to_many
            ),
        )

    @cached_property
    def related_objects(self) -> ImmutableList:
        """
        Return all related objects pointing to the current model. The related
        objects can come from a one-to-one, one-to-many, or many-to-many field
        relation type.

        Private API intended only to be used by Plain itself; get_fields()
        combined with filtering of field properties is the public API for
        obtaining this field list.
        """
        all_related_fields = self._get_fields(
            forward=False, reverse=True, include_hidden=True
        )
        return make_immutable_fields_list(
            "related_objects",
            (
                obj
                for obj in all_related_fields
                if not obj.hidden or obj.field.many_to_many
            ),
        )

    @cached_property
    def _forward_fields_map(self) -> dict[str, Any]:
        res = {}
        fields = self._get_fields(reverse=False)
        for field in fields:
            res[field.name] = field
            # Due to the way Plain's internals work, get_field() should also
            # be able to fetch a field by attname. In the case of a concrete
            # field with relation, includes the *_id name too
            try:
                res[field.attname] = field
            except AttributeError:
                pass
        return res

    @cached_property
    def fields_map(self) -> dict[str, Any]:
        res = {}
        fields = self._get_fields(forward=False, include_hidden=True)
        for field in fields:
            res[field.name] = field
            # Due to the way Plain's internals work, get_field() should also
            # be able to fetch a field by attname. In the case of a concrete
            # field with relation, includes the *_id name too
            try:
                res[field.attname] = field
            except AttributeError:
                pass
        return res

    def get_field(self, field_name: str) -> Any:
        """
        Return a field instance given the name of a forward or reverse field.
        """
        try:
            # In order to avoid premature loading of the relation tree
            # (expensive) we prefer checking if the field is a forward field.
            return self._forward_fields_map[field_name]
        except KeyError:
            # If the app registry is not ready, reverse fields are
            # unavailable, therefore we throw a FieldDoesNotExist exception.
            if not self.models_registry.ready:
                raise FieldDoesNotExist(
                    f"{self.model} has no field named '{field_name}'. The app cache isn't ready yet, "
                    "so if this is an auto-created related field, it won't "
                    "be available yet."
                )

        try:
            # Retrieve field instance by name from cached or just-computed
            # field map.
            return self.fields_map[field_name]
        except KeyError:
            raise FieldDoesNotExist(f"{self.model} has no field named '{field_name}'")

    def _populate_directed_relation_graph(self) -> Any:
        """
        This method is used by each model to find its reverse objects. As this
        method is very expensive and is accessed frequently (it looks up every
        field in a model, in every app), it is computed on first access and then
        is set as a property on every model.
        """
        related_objects_graph: defaultdict[str, list[Any]] = defaultdict(list)

        all_models = self.models_registry.get_models()
        for model in all_models:
            meta = model._model_meta

            fields_with_relations = (
                f
                for f in meta._get_fields(reverse=False)
                if f.is_relation and f.related_model is not None
            )
            for f in fields_with_relations:
                if not isinstance(f.remote_field.model, str):
                    remote_label = f.remote_field.model.model_options.label
                    related_objects_graph[remote_label].append(f)

        for model in all_models:
            # Set the relation_tree using the internal __dict__. In this way
            # we avoid calling the cached property. In attribute lookup,
            # __dict__ takes precedence over a data descriptor (such as
            # @cached_property). This means that the _model_meta._relation_tree is
            # only called if related_objects is not in __dict__.
            related_objects = related_objects_graph[model.model_options.label]
            model._model_meta.__dict__["_relation_tree"] = related_objects
        # It seems it is possible that self is not in all_models, so guard
        # against that with default for get().
        return self.__dict__.get("_relation_tree", EMPTY_RELATION_TREE)

    @cached_property
    def _relation_tree(self) -> Any:
        return self._populate_directed_relation_graph()

    def _expire_cache(self, forward: bool = True, reverse: bool = True) -> None:
        # This method is usually called by packages.cache_clear(), when the
        # registry is finalized, or when a new field is added.
        if forward:
            for cache_key in self.FORWARD_PROPERTIES:
                if cache_key in self.__dict__:
                    delattr(self, cache_key)
        if reverse:
            for cache_key in self.REVERSE_PROPERTIES:
                if cache_key in self.__dict__:
                    delattr(self, cache_key)
        self._get_fields_cache = {}

    def get_fields(self, include_hidden: bool = False) -> ImmutableList:
        """
        Return a list of fields associated to the model. By default, include
        forward and reverse fields, fields derived from inheritance, but not
        hidden fields. The returned fields can be changed using the parameters:

        - include_hidden:  include fields that have a related_name that
                           starts with a "+"
        """
        return self._get_fields(include_hidden=include_hidden)

    def _get_fields(
        self,
        forward: bool = True,
        reverse: bool = True,
        include_hidden: bool = False,
        seen_models: set[type[Any]] | None = None,
    ) -> ImmutableList:
        """
        Internal helper function to return fields of the model.
        * If forward=True, then fields defined on this model are returned.
        * If reverse=True, then relations pointing to this model are returned.
        * If include_hidden=True, then fields with is_hidden=True are returned.
        """

        # This helper function is used to allow recursion in ``get_fields()``
        # implementation and to provide a fast way for Plain's internals to
        # access specific subsets of fields.

        # We must keep track of which models we have already seen. Otherwise we
        # could include the same field multiple times from different models.
        topmost_call = seen_models is None
        if seen_models is None:
            seen_models = set()
        seen_models.add(self.model)

        # Creates a cache key composed of all arguments
        cache_key = (forward, reverse, include_hidden, topmost_call)

        try:
            # In order to avoid list manipulation. Always return a shallow copy
            # of the results.
            return self._get_fields_cache[cache_key]
        except KeyError:
            pass

        fields = []

        if reverse:
            # Tree is computed once and cached until the app cache is expired.
            # It is composed of a list of fields pointing to the current model
            # from other models.
            all_fields = self._relation_tree
            for field in all_fields:
                # If hidden fields should be included or the relation is not
                # intentionally hidden, add to the fields dict.
                if include_hidden or not field.remote_field.hidden:
                    fields.append(field.remote_field)

        if forward:
            fields += self.local_fields
            fields += self.local_many_to_many

        # In order to avoid list manipulation. Always
        # return a shallow copy of the results
        fields = make_immutable_fields_list("get_fields()", fields)

        # Store result into cache for later access
        self._get_fields_cache[cache_key] = fields
        return fields

    @cached_property
    def _property_names(self) -> frozenset[str]:
        """Return a set of the names of the properties defined on the model."""
        names = []
        for name in dir(self.model):
            attr = inspect.getattr_static(self.model, name)
            if isinstance(attr, property):
                names.append(name)
        return frozenset(names)

    @cached_property
    def _non_pk_concrete_field_names(self) -> frozenset[str]:
        """
        Return a set of the non-primary key concrete field names defined on the model.
        """
        names = []
        for field in self.concrete_fields:
            if not field.primary_key:
                names.append(field.name)
                if field.name != field.attname:
                    names.append(field.attname)
        return frozenset(names)

    @cached_property
    def db_returning_fields(self) -> list[Field]:
        """
        Private API intended only to be used by Plain itself.
        Fields to be returned after a database insert.
        """
        return [
            field
            for field in self._get_fields(forward=True, reverse=False)
            if getattr(field, "db_returning", False)
        ]
