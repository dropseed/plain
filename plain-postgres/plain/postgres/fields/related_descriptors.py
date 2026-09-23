"""
Accessors for related objects.

When a field defines a relation between two models, the forward model provides
an attribute to access related instances. Reverse accessors must be explicitly
defined using ReverseForeignKey or ReverseManyToMany descriptors.

Accessors are implemented as descriptors in order to customize access and
assignment. This module defines the descriptor classes.

Forward accessors follow foreign keys. Reverse accessors trace them back. For
example, with the following models::

    class Parent(Model):
        children: ClassVar[ReverseForeignKey[Child]] = ReverseForeignKey(to="Child", field="parent")

    class Child(Model):
        parent: Field[Parent] = ForeignKeyField(Parent, on_delete=CASCADE)

 ``child.parent`` is a forward foreign key relation. ``parent.children`` is a
reverse foreign key relation.

1. Related instance on the forward side of a foreign key relation:
   ``ForwardForeignKeyDescriptor``.

2. Related objects manager for related instances on the forward or reverse
   sides of a many-to-many relation: ``ForwardManyToManyDescriptor``.

   Many-to-many relations are symmetrical. The syntax of Plain models
   requires declaring them on one side but that's an implementation detail.
   They could be declared on the other side without any change in behavior.

Reverse relations must be explicitly defined using ``ReverseForeignKey`` or
``ReverseManyToMany`` descriptors on the model class.
"""

from functools import cached_property
from typing import Any

from plain.postgres.query import QuerySet
from plain.utils.functional import LazyObject

from .related_managers import ManyToManyManager


class ForwardForeignKeyDescriptor:
    """
    Accessor to the related object on the forward side of a foreign key relation.

    In the example::

        class Child(Model):
            parent: Field[Parent] = ForeignKeyField(Parent, on_delete=postgres.CASCADE)

    ``Child.parent`` is a ``ForwardForeignKeyDescriptor`` instance.
    """

    def __init__(self, field_with_rel: Any) -> None:
        self._field = field_with_rel

    @cached_property
    def RelatedObjectDoesNotExist(self) -> type:
        # The exception can't be created at initialization time since the
        # related model might not be resolved yet; `self._field.model` might
        # still be a string model reference.
        return type(
            "RelatedObjectDoesNotExist",
            (self._field.remote_field.model.DoesNotExist, AttributeError),
            {
                "__module__": self._field.model.__module__,
                "__qualname__": f"{self._field.model.__qualname__}.{self._field.name}.RelatedObjectDoesNotExist",
            },
        )

    def _is_cached(self, instance: Any) -> bool:
        return self._field.is_cached(instance)

    def _get_queryset(self) -> QuerySet:
        qs = self._field.remote_field.model._model_meta.base_queryset
        return qs.all()

    def _get_prefetch_queryset(
        self, instances: list[Any], queryset: QuerySet | None = None
    ) -> tuple[QuerySet, Any, Any, bool, str, bool]:
        if queryset is None:
            queryset = self._get_queryset()

        rel_obj_attr = self._field.get_foreign_related_value
        instance_attr = self._field.get_local_related_value
        related_field = self._field.target_field

        # A foreign key is single-column, so prefetch with a join-less IN query.
        query = {
            f"{related_field.name}__in": {instance_attr(inst) for inst in instances}
        }
        queryset = queryset.filter(**query)

        return (
            queryset,
            rel_obj_attr,
            instance_attr,
            True,
            self._field.get_cache_name(),
            False,
        )

    def __get__(self, instance: Any | None, cls: type | None = None) -> Any:
        """
        Get the related instance through the forward relation.

        With the example above, when getting ``child.parent``:

        - ``self`` is the descriptor managing the ``parent`` attribute
        - ``instance`` is the ``child`` instance
        - ``cls`` is the ``Child`` class (we don't need it)

        Class-level access (``Child.parent``) returns the descriptor itself,
        the ordinary convention. Traversal for typed where() is served by
        ``__getattr__`` below rather than by handing back a proxy.
        """
        if instance is None:
            return self

        # The related object is cached on the model state -- by join(),
        # prefetch, the reverse accessor, a prior access, or assignment.
        try:
            rel_obj = self._field.get_cached_value(instance)
        except KeyError:
            # _get_raw_value loads the foreign key column on demand if it was
            # deferred (.only()/.defer()), so we always see the real key here.
            pk_value = self._field._get_raw_value(instance)
            rel_obj = None
            if pk_value is not None:
                remote_model = self._field.remote_field.model
                target_name = self._field.target_field.name
                assert target_name is not None
                # The database FK constraint guarantees the row exists, so build
                # a partial related instance with only its primary key loaded --
                # no query. Accessing any other field triggers the full-row
                # deferred load.
                rel_obj = remote_model.from_db([target_name], [pk_value])
            self._field.set_cached_value(instance, rel_obj)

        # Checked on every access, including a cached None: a non-nullable
        # foreign key with no value must raise consistently, not just once.
        if rel_obj is None and not self._field.allow_null:
            raise self.RelatedObjectDoesNotExist(
                f"{self._field.model.__name__} has no {self._field.name}."
            )
        return rel_obj

    def _build_typed_ref(self) -> Any:
        """The traversal entry point for this relation.

        Built lazily, and cached by `__getattr__` rather than by
        `cached_property`: this can raise `UnresolvedRelationError`, and an
        AttributeError raised inside a descriptor's `__get__` makes Python
        fall back to `__getattr__`, which would replace the useful message
        with a bare "no attribute '_typed_ref'".

        The import is local because `related_typed` reaches `fields.related`,
        which imports this module at load time.
        """
        from plain.postgres.fields.related_typed import (
            RelatedFieldRef,
            unresolved_relation_error,
        )

        try:
            model = self._field.remote_field.model
        except TypeError:
            # `ForeignObjectRel.model` raises TypeError while the target is
            # still a string, which would escape __getattr__ as a TypeError and
            # make `hasattr` raise instead of returning False.
            raise unresolved_relation_error(
                self._field.name, str(self._field.remote_field.model_ref)
            ) from None

        return RelatedFieldRef(
            model=model,
            prefix=self._field.name,
            target_name=self._field.target_field.name,
            # The traversal starts here, on the model the relation is declared
            # on -- that is the model a condition built through it belongs to.
            source_model=self._field.model,
        )

    def __getattr__(self, name: str) -> Any:
        """Walk class-level attribute access into the related model, so typed
        where() can build joined lookups:

            Child.parent.name.equals("x")    →    Q(parent__name="x")

        Only names this descriptor doesn't define reach here, and every
        attribute it does define is ``_``-prefixed -- which model fields can
        never be (``Meta`` skips ``_``-prefixed attributes when it collects
        them), so a related field can't be shadowed by descriptor internals.

        Delegated to `RelatedFieldRef` so the first hop follows exactly the
        same rule as every later one.
        """
        if name.startswith("_"):
            # Internals, and anything a field could never be named.
            raise AttributeError(name)
        ref = self.__dict__.get("_typed_ref")
        if ref is None:
            ref = self.__dict__["_typed_ref"] = self._build_typed_ref()
        return getattr(ref, name)

    def __set__(self, instance: Any, value: Any) -> None:
        """
        Set the related object (or its raw key) through the forward relation.

        Accepts a related model instance, a bare primary key value, or None::

            child.parent = parent_instance
            child.parent = 5
            child.parent = None
        """
        from plain.postgres.base import Model

        # A LazyObject (e.g. request.user) must be evaluated before use.
        if isinstance(value, LazyObject):
            value = value if value else None

        name = self._field.name
        assert name is not None
        remote_field = self._field.remote_field

        if value is None:
            instance.__dict__[name] = None
            self._field.set_cached_value(instance, None)
            return

        if isinstance(value, remote_field.model):
            # A related model instance: store its key, cache the object.
            instance.__dict__[name] = getattr(value, self._field.target_field.name)
            self._field.set_cached_value(instance, value)
            return

        if isinstance(value, Model | bool):
            # A wrong-model instance, or a bool (which would silently coerce to
            # the key 0/1 via int) -- reject rather than store a bogus key.
            raise TypeError(
                f'Cannot assign "{value!r}": '
                f'"{instance.model_options.object_name}.{self._field.name}" must be a '
                f'"{remote_field.model.model_options.object_name}" instance or a '
                f"primary key value."
            )

        # A bare related key value (e.g. child.parent = 5).
        new_value = self._field.to_python(value)
        # On an actual key change, drop the now-stale forward cache.
        # Re-storing the same key (e.g. by clean_fields) keeps the cache.
        if instance.__dict__.get(name) != new_value and self._field.is_cached(instance):
            self._field.delete_cached_value(instance)
        instance.__dict__[name] = new_value

    def __delete__(self, instance: Any) -> None:
        """Delete the foreign key value, clearing any cached related object."""
        try:
            del instance.__dict__[self._field.name]
        except KeyError:
            raise AttributeError(
                f"{instance.__class__.__name__!r} object has no attribute "
                f"{self._field.name!r}"
            )
        if self._field.is_cached(instance):
            self._field.delete_cached_value(instance)

    def __reduce__(self) -> tuple[Any, tuple[Any, str]]:
        """
        Pickling should return the instance attached by self._field on the
        model, not a new copy of that descriptor.

        Class access returns the descriptor, so ``getattr`` retrieves the
        instance directly from the model.
        """
        return getattr, (self._field.model, self._field.name)


class ForwardManyToManyDescriptor:
    """
    Accessor to the related objects manager on the forward side of a
    many-to-many relation.

    In the example::

        class Pizza(Model):
            toppings: ManyToManyField[Topping] = ManyToManyField(Topping, through=PizzaTopping)

    ``Pizza.toppings`` is a ``ForwardManyToManyDescriptor`` instance.
    """

    def __init__(self, rel: Any) -> None:
        self.rel = rel
        self.field = rel.field

    def __get__(
        self, instance: Any | None, cls: type | None = None
    ) -> ForwardManyToManyDescriptor | Any:
        """Get the related manager when the descriptor is accessed."""
        if instance is None:
            return self
        return ManyToManyManager(
            instance=instance,
            field=self.rel.field,
            through=self.rel.through,
            related_model=self.rel.model,
            is_reverse=False,
            symmetrical=self.rel.symmetrical,
        )

    def __set__(self, instance: Any, value: Any) -> None:
        """Prevent direct assignment to the relation."""
        raise TypeError(
            f"Direct assignment to the forward side of a many-to-many set is prohibited. Use {self.field.name}.set() instead.",
        )

    @property
    def through(self) -> Any:
        # through is provided so that you have easy access to the through
        # model (Book.authors.through) for inlines, etc. This is done as
        # a property to ensure that the fully resolved value is returned.
        return self.rel.through
