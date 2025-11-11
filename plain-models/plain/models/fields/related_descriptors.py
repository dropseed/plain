"""
Accessors for related objects.

When a field defines a relation between two models, each model class provides
an attribute to access related instances of the other model class (unless the
reverse accessor has been disabled with related_name='+').

Accessors are implemented as descriptors in order to customize access and
assignment. This module defines the descriptor classes.

Forward accessors follow foreign keys. Reverse accessors trace them back. For
example, with the following models::

    class Parent(Model):
        pass

    class Child(Model):
        parent = ForeignKey(Parent, related_name='children')

 ``child.parent`` is a forward many-to-one relation. ``parent.children`` is a
reverse many-to-one relation.

1. Related instance on the forward side of a many-to-one relation:
   ``ForwardManyToOneDescriptor``.

   Uniqueness of foreign key values is irrelevant to accessing the related
   instance, making the many-to-one and one-to-one cases identical as far as
   the descriptor is concerned. The constraint is checked upstream (unicity
   validation in forms) or downstream (unique indexes in the database).

2. Related objects manager for related instances on the reverse side of a
   many-to-one relation: ``ReverseManyToOneDescriptor``.

   Unlike the previous two classes, this one provides access to a collection
   of objects. It returns a manager rather than an instance.

3. Related objects manager for related instances on the forward or reverse
   sides of a many-to-many relation: ``ManyToManyDescriptor``.

   Many-to-many relations are symmetrical. The syntax of Plain models
   requires declaring them on one side but that's an implementation detail.
   They could be declared on the other side without any change in behavior.
   Therefore the forward and reverse descriptors can be the same.

   If you're looking for ``ForwardManyToManyDescriptor`` or
   ``ReverseManyToManyDescriptor``, use ``ManyToManyDescriptor`` instead.
"""

from __future__ import annotations

from functools import cached_property
from typing import Any

from plain.models.query import QuerySet
from plain.utils.functional import LazyObject

from .related_managers import (
    ForwardManyToManyManager,
    ReverseManyToManyManager,
    ReverseManyToOneManager,
)


class ForwardManyToOneDescriptor:
    """
    Accessor to the related object on the forward side of a many-to-one relation.

    In the example::

        class Child(Model):
            parent = ForeignKey(Parent, related_name='children')

    ``Child.parent`` is a ``ForwardManyToOneDescriptor`` instance.
    """

    def __init__(self, field_with_rel: Any) -> None:
        self.field = field_with_rel

    @cached_property
    def RelatedObjectDoesNotExist(self) -> type:
        # The exception can't be created at initialization time since the
        # related model might not be resolved yet; `self.field.model` might
        # still be a string model reference.
        return type(
            "RelatedObjectDoesNotExist",
            (self.field.remote_field.model.DoesNotExist, AttributeError),
            {
                "__module__": self.field.model.__module__,
                "__qualname__": f"{self.field.model.__qualname__}.{self.field.name}.RelatedObjectDoesNotExist",
            },
        )

    def is_cached(self, instance: Any) -> bool:
        return self.field.is_cached(instance)

    def get_queryset(self) -> QuerySet:
        qs = self.field.remote_field.model._model_meta.base_queryset
        return qs.all()

    def get_prefetch_queryset(
        self, instances: list[Any], queryset: QuerySet | None = None
    ) -> tuple[QuerySet, Any, Any, bool, str, bool]:
        if queryset is None:
            queryset = self.get_queryset()

        rel_obj_attr = self.field.get_foreign_related_value
        instance_attr = self.field.get_local_related_value
        instances_dict = {instance_attr(inst): inst for inst in instances}
        related_field = self.field.foreign_related_fields[0]
        remote_field = self.field.remote_field

        # FIXME: This will need to be revisited when we introduce support for
        # composite fields. In the meantime we take this practical approach to
        # solve a regression on 1.6 when the reverse manager in hidden
        # (related_name ends with a '+'). Refs #21410.
        # The check for len(...) == 1 is a special case that allows the query
        # to be join-less and smaller. Refs #21760.
        if remote_field.is_hidden() or len(self.field.foreign_related_fields) == 1:
            query = {
                f"{related_field.name}__in": {
                    instance_attr(inst)[0] for inst in instances
                }
            }
        else:
            query = {f"{self.field.related_query_name()}__in": instances}
        queryset = queryset.filter(**query)

        # Since we're going to assign directly in the cache,
        # we must manage the reverse relation cache manually.
        if not remote_field.multiple:
            for rel_obj in queryset:
                instance = instances_dict[rel_obj_attr(rel_obj)]
                remote_field.set_cached_value(rel_obj, instance)
        return (
            queryset,
            rel_obj_attr,
            instance_attr,
            True,
            self.field.get_cache_name(),
            False,
        )

    def get_object(self, instance: Any) -> Any:
        qs = self.get_queryset()
        # Assuming the database enforces foreign keys, this won't fail.
        return qs.get(self.field.get_reverse_related_filter(instance))

    def __get__(
        self, instance: Any | None, cls: type | None = None
    ) -> ForwardManyToOneDescriptor | Any | None:
        """
        Get the related instance through the forward relation.

        With the example above, when getting ``child.parent``:

        - ``self`` is the descriptor managing the ``parent`` attribute
        - ``instance`` is the ``child`` instance
        - ``cls`` is the ``Child`` class (we don't need it)
        """
        if instance is None:
            return self

        # The related instance is loaded from the database and then cached
        # by the field on the model instance state. It can also be pre-cached
        # by the reverse accessor.
        try:
            rel_obj = self.field.get_cached_value(instance)
        except KeyError:
            has_value = None not in self.field.get_local_related_value(instance)
            rel_obj = None

            if rel_obj is None and has_value:
                rel_obj = self.get_object(instance)
                remote_field = self.field.remote_field
                # If this is a one-to-one relation, set the reverse accessor
                # cache on the related object to the current instance to avoid
                # an extra SQL query if it's accessed later on.
                if not remote_field.multiple:
                    remote_field.set_cached_value(rel_obj, instance)
            self.field.set_cached_value(instance, rel_obj)

        if rel_obj is None and not self.field.allow_null:
            raise self.RelatedObjectDoesNotExist(
                f"{self.field.model.__name__} has no {self.field.name}."
            )
        else:
            return rel_obj

    def __set__(self, instance: Any, value: Any) -> None:
        """
        Set the related instance through the forward relation.

        With the example above, when setting ``child.parent = parent``:

        - ``self`` is the descriptor managing the ``parent`` attribute
        - ``instance`` is the ``child`` instance
        - ``value`` is the ``parent`` instance on the right of the equal sign
        """
        # If value is a LazyObject, force its evaluation. For ForeignKey fields,
        # the value should only be None or a model instance, never a boolean or
        # other type.
        if isinstance(value, LazyObject):
            # This forces evaluation: if it's None, value becomes None;
            # if it's a User instance, value becomes that instance.
            value = value if value else None

        # An object must be an instance of the related class.
        if value is not None and not isinstance(value, self.field.remote_field.model):
            raise ValueError(
                f'Cannot assign "{value!r}": "{instance.model_options.object_name}.{self.field.name}" must be a "{self.field.remote_field.model.model_options.object_name}" instance.'
            )
        remote_field = self.field.remote_field
        # If we're setting the value of a OneToOneField to None, we need to clear
        # out the cache on any old related object. Otherwise, deleting the
        # previously-related object will also cause this object to be deleted,
        # which is wrong.
        if value is None:
            # Look up the previously-related object, which may still be available
            # since we've not yet cleared out the related field.
            # Use the cache directly, instead of the accessor; if we haven't
            # populated the cache, then we don't care - we're only accessing
            # the object to invalidate the accessor cache, so there's no
            # need to populate the cache just to expire it again.
            related = self.field.get_cached_value(instance, default=None)

            # If we've got an old related object, we need to clear out its
            # cache. This cache also might not exist if the related object
            # hasn't been accessed yet.
            if related is not None:
                remote_field.set_cached_value(related, None)

            for lh_field, rh_field in self.field.related_fields:
                setattr(instance, lh_field.attname, None)

        # Set the values of the related field.
        else:
            for lh_field, rh_field in self.field.related_fields:
                setattr(instance, lh_field.attname, getattr(value, rh_field.attname))

        # Set the related instance cache used by __get__ to avoid an SQL query
        # when accessing the attribute we just set.
        self.field.set_cached_value(instance, value)

        # If this is a one-to-one relation, set the reverse accessor cache on
        # the related object to the current instance to avoid an extra SQL
        # query if it's accessed later on.
        if value is not None and not remote_field.multiple:
            remote_field.set_cached_value(value, instance)

    def __reduce__(self) -> tuple[Any, tuple[Any, str]]:
        """
        Pickling should return the instance attached by self.field on the
        model, not a new copy of that descriptor. Use getattr() to retrieve
        the instance directly from the model.
        """
        return getattr, (self.field.model, self.field.name)


class RelationDescriptorBase:
    """
    Base class for relation descriptors that don't allow direct assignment.

    This is used for descriptors that manage collections of related objects
    (reverse FK and M2M relations). Forward FK relations don't inherit from
    this because they allow direct assignment.
    """

    def __init__(self, rel: Any) -> None:
        self.rel = rel
        self.field = rel.field

    def __get__(
        self, instance: Any | None, cls: type | None = None
    ) -> RelationDescriptorBase | Any:
        """
        Get the related manager when the descriptor is accessed.

        Subclasses must implement get_related_manager().
        """
        if instance is None:
            return self
        return self.get_related_manager(instance)

    def get_related_manager(self, instance: Any) -> Any:
        """Return the appropriate manager for this relation."""
        raise NotImplementedError(
            f"{self.__class__.__name__} must implement get_related_manager()"
        )

    def _get_set_deprecation_msg_params(self) -> tuple[str, str]:
        """Return parameters for the error message when direct assignment is attempted."""
        raise NotImplementedError(
            f"{self.__class__.__name__} must implement _get_set_deprecation_msg_params()"
        )

    def __set__(self, instance: Any, value: Any) -> None:
        """Prevent direct assignment to the relation."""
        raise TypeError(
            "Direct assignment to the {} is prohibited. Use {}.set() instead.".format(
                *self._get_set_deprecation_msg_params()
            ),
        )


class ReverseManyToOneDescriptor(RelationDescriptorBase):
    """
    Accessor to the related objects manager on the reverse side of a
    many-to-one relation.

    In the example::

        class Child(Model):
            parent = ForeignKey(Parent, related_name='children')

    ``Parent.children`` is a ``ReverseManyToOneDescriptor`` instance.

    Most of the implementation is delegated to the ReverseManyToOneManager class.
    """

    def get_related_manager(self, instance: Any) -> ReverseManyToOneManager:
        """Return the ReverseManyToOneManager for this relation."""
        return ReverseManyToOneManager(instance, self.rel)

    def _get_set_deprecation_msg_params(self) -> tuple[str, str]:
        return (
            "reverse side of a related set",
            self.rel.get_accessor_name(),
        )


class ForwardManyToManyDescriptor(RelationDescriptorBase):
    """
    Accessor to the related objects manager on the forward side of a
    many-to-many relation.

    In the example::

        class Pizza(Model):
            toppings = ManyToManyField(Topping, related_name='pizzas')

    ``Pizza.toppings`` is a ``ForwardManyToManyDescriptor`` instance.
    """

    @property
    def through(self) -> Any:
        # through is provided so that you have easy access to the through
        # model (Book.authors.through) for inlines, etc. This is done as
        # a property to ensure that the fully resolved value is returned.
        return self.rel.through

    def get_related_manager(self, instance: Any) -> ForwardManyToManyManager:
        """Return the ForwardManyToManyManager for this relation."""
        return ForwardManyToManyManager(instance, self.rel)

    def _get_set_deprecation_msg_params(self) -> tuple[str, str]:
        return (
            "forward side of a many-to-many set",
            self.field.name,
        )


class ReverseManyToManyDescriptor(RelationDescriptorBase):
    """
    Accessor to the related objects manager on the reverse side of a
    many-to-many relation.

    In the example::

        class Pizza(Model):
            toppings = ManyToManyField(Topping, related_name='pizzas')

    ``Topping.pizzas`` is a ``ReverseManyToManyDescriptor`` instance.
    """

    @property
    def through(self) -> Any:
        # through is provided so that you have easy access to the through
        # model (Book.authors.through) for inlines, etc. This is done as
        # a property to ensure that the fully resolved value is returned.
        return self.rel.through

    def get_related_manager(self, instance: Any) -> ReverseManyToManyManager:
        """Return the ReverseManyToManyManager for this relation."""
        return ReverseManyToManyManager(instance, self.rel)

    def _get_set_deprecation_msg_params(self) -> tuple[str, str]:
        return (
            "reverse side of a many-to-many set",
            self.rel.get_accessor_name(),
        )
