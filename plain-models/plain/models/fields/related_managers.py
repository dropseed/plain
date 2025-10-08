"""
Managers for related objects.

These managers provide the API for working with collections of related objects
through foreign key and many-to-many relationships.
"""

from __future__ import annotations

from typing import Any

from plain.models import transaction
from plain.models.db import NotSupportedError, db_connection
from plain.models.expressions import Window
from plain.models.functions import RowNumber
from plain.models.lookups import GreaterThan, LessThanOrEqual
from plain.models.query import QuerySet
from plain.models.query_utils import Q
from plain.models.utils import resolve_callables


def _filter_prefetch_queryset(
    queryset: QuerySet, field_name: str, instances: Any
) -> QuerySet:
    predicate = Q(**{f"{field_name}__in": instances})
    if queryset.sql_query.is_sliced:
        if not db_connection.features.supports_over_clause:
            raise NotSupportedError(
                "Prefetching from a limited queryset is only supported on backends "
                "that support window functions."
            )
        low_mark, high_mark = queryset.sql_query.low_mark, queryset.sql_query.high_mark
        order_by = [
            expr for expr, _ in queryset.sql_query.get_compiler().get_order_by()
        ]
        window = Window(RowNumber(), partition_by=field_name, order_by=order_by)
        predicate &= GreaterThan(window, low_mark)  # type: ignore[unsupported-operator]
        if high_mark is not None:
            predicate &= LessThanOrEqual(window, high_mark)  # type: ignore[unsupported-operator]
        queryset.sql_query.clear_limits()
    return queryset.filter(predicate)


class BaseRelatedManager:
    """
    Base class for all related object managers.

    All related managers should have a 'query' property that returns a QuerySet.
    """

    @property
    def query(self) -> QuerySet:
        """Access the QuerySet for this relationship."""
        return self.get_queryset()

    def get_queryset(self) -> QuerySet:
        """Return the QuerySet for this relationship."""
        raise NotImplementedError("Subclasses must implement get_queryset()")


class ReverseManyToOneManager(BaseRelatedManager):
    """
    Manager for the reverse side of a many-to-one relation.

    This manager adds behaviors specific to many-to-one relations.
    """

    def __init__(self, instance: Any, rel: Any):
        self.model = rel.related_model
        self.instance = instance
        self.field = rel.field
        self.core_filters = {self.field.name: instance}
        self.allow_null = rel.field.allow_null

    def _check_fk_val(self) -> None:
        for field in self.field.foreign_related_fields:
            if getattr(self.instance, field.attname) is None:
                raise ValueError(
                    f'"{self.instance!r}" needs to have a value for field '
                    f'"{field.attname}" before this relationship can be used.'
                )

    def _apply_rel_filters(self, queryset: QuerySet) -> QuerySet:
        """
        Filter the queryset for the instance this manager is bound to.
        """
        from plain.models.exceptions import FieldError

        queryset._defer_next_filter = True
        queryset = queryset.filter(**self.core_filters)
        for field in self.field.foreign_related_fields:
            val = getattr(self.instance, field.attname)
            if val is None:
                return queryset.none()
        if self.field.many_to_one:
            # Guard against field-like objects such as GenericRelation
            # that abuse create_reverse_many_to_one_manager() with reverse
            # one-to-many relationships instead and break known related
            # objects assignment.
            try:
                target_field = self.field.target_field
            except FieldError:
                # The relationship has multiple target fields. Use a tuple
                # for related object id.
                rel_obj_id = tuple(
                    [
                        getattr(self.instance, target_field.attname)
                        for target_field in self.field.path_infos[-1].target_fields
                    ]
                )
            else:
                rel_obj_id = getattr(self.instance, target_field.attname)
            queryset._known_related_objects = {self.field: {rel_obj_id: self.instance}}
        return queryset

    def _remove_prefetched_objects(self) -> None:
        try:
            self.instance._prefetched_objects_cache.pop(
                self.field.remote_field.get_cache_name()
            )
        except (AttributeError, KeyError):
            pass  # nothing to clear from cache

    def get_queryset(self) -> QuerySet:
        # Even if this relation is not to primary key, we require still primary key value.
        # The wish is that the instance has been already saved to DB,
        # although having a primary key value isn't a guarantee of that.
        if self.instance.id is None:
            raise ValueError(
                f"{self.instance.__class__.__name__!r} instance needs to have a "
                f"primary key value before this relationship can be used."
            )
        try:
            return self.instance._prefetched_objects_cache[
                self.field.remote_field.get_cache_name()
            ]
        except (AttributeError, KeyError):
            queryset = self.model.query
            return self._apply_rel_filters(queryset)

    def get_prefetch_queryset(
        self, instances: Any, queryset: QuerySet | None = None
    ) -> tuple[QuerySet, Any, Any, bool, str, bool]:
        if queryset is None:
            queryset = self.model.query

        rel_obj_attr = self.field.get_local_related_value
        instance_attr = self.field.get_foreign_related_value
        instances_dict = {instance_attr(inst): inst for inst in instances}
        queryset = _filter_prefetch_queryset(queryset, self.field.name, instances)

        # Since we just bypassed this class' get_queryset(), we must manage
        # the reverse relation manually.
        for rel_obj in queryset:
            if not self.field.is_cached(rel_obj):
                instance = instances_dict[rel_obj_attr(rel_obj)]
                setattr(rel_obj, self.field.name, instance)
        cache_name = self.field.remote_field.get_cache_name()
        return queryset, rel_obj_attr, instance_attr, False, cache_name, False

    def add(self, *objs: Any, bulk: bool = True) -> None:
        self._check_fk_val()
        self._remove_prefetched_objects()

        def check_and_update_obj(obj: Any) -> None:
            if not isinstance(obj, self.model):
                raise TypeError(
                    f"'{self.model.model_options.object_name}' instance expected, got {obj!r}"
                )
            setattr(obj, self.field.name, self.instance)

        if bulk:
            ids = []
            for obj in objs:
                check_and_update_obj(obj)
                if obj._state.adding:
                    raise ValueError(
                        f"{obj!r} instance isn't saved. Use bulk=False or save "
                        "the object first."
                    )
                ids.append(obj.id)
            self.model._model_meta.base_queryset.filter(id__in=ids).update(
                **{
                    self.field.name: self.instance,
                }
            )
        else:
            with transaction.atomic(savepoint=False):
                for obj in objs:
                    check_and_update_obj(obj)
                    obj.save()

    def create(self, **kwargs: Any) -> Any:
        self._check_fk_val()
        kwargs[self.field.name] = self.instance
        return self.model.query.create(**kwargs)

    def get_or_create(self, **kwargs: Any) -> tuple[Any, bool]:
        self._check_fk_val()
        kwargs[self.field.name] = self.instance
        return self.model.query.get_or_create(**kwargs)

    def update_or_create(self, **kwargs: Any) -> tuple[Any, bool]:
        self._check_fk_val()
        kwargs[self.field.name] = self.instance
        return self.model.query.update_or_create(**kwargs)

    def remove(self, *objs: Any, bulk: bool = True) -> None:
        # remove() is only provided if the ForeignKey can have a value of null
        if not self.allow_null:
            raise AttributeError(
                f"Cannot call remove() on a related manager for field "
                f"{self.field.name} where null=False."
            )
        if not objs:
            return
        self._check_fk_val()
        val = self.field.get_foreign_related_value(self.instance)
        old_ids = set()
        for obj in objs:
            if not isinstance(obj, self.model):
                raise TypeError(
                    f"'{self.model.model_options.object_name}' instance expected, got {obj!r}"
                )
            # Is obj actually part of this descriptor set?
            if self.field.get_local_related_value(obj) == val:
                old_ids.add(obj.id)
            else:
                raise self.field.remote_field.model.DoesNotExist(
                    f"{obj!r} is not related to {self.instance!r}."
                )
        self._clear(self.query.filter(id__in=old_ids), bulk)

    def clear(self, *, bulk: bool = True) -> None:
        # clear() is only provided if the ForeignKey can have a value of null
        if not self.allow_null:
            raise AttributeError(
                f"Cannot call clear() on a related manager for field "
                f"{self.field.name} where null=False."
            )
        self._check_fk_val()
        self._clear(self.query, bulk)

    def _clear(self, queryset: QuerySet, bulk: bool) -> None:
        self._remove_prefetched_objects()
        if bulk:
            # `QuerySet.update()` is intrinsically atomic.
            queryset.update(**{self.field.name: None})
        else:
            with transaction.atomic(savepoint=False):
                for obj in queryset:
                    setattr(obj, self.field.name, None)
                    obj.save(update_fields=[self.field.name])

    def set(self, objs: Any, *, bulk: bool = True, clear: bool = False) -> None:
        self._check_fk_val()
        # Force evaluation of `objs` in case it's a queryset whose value
        # could be affected by `manager.clear()`. Refs #19816.
        objs = tuple(objs)

        if self.field.allow_null:
            with transaction.atomic(savepoint=False):
                if clear:
                    self.clear(bulk=bulk)
                    self.add(*objs, bulk=bulk)
                else:
                    old_objs = set(self.query.all())
                    new_objs = []
                    for obj in objs:
                        if obj in old_objs:
                            old_objs.remove(obj)
                        else:
                            new_objs.append(obj)

                    self.remove(*old_objs, bulk=bulk)
                    self.add(*new_objs, bulk=bulk)
        else:
            self.add(*objs, bulk=bulk)


class BaseManyToManyManager(BaseRelatedManager):
    """
    Base class for many-to-many managers with common functionality.

    Subclasses must set these attributes in __init__:
    - model
    - query_field_name
    - prefetch_cache_name
    - source_field_name
    - target_field_name
    - symmetrical (for forward relations)
    """

    def __init__(self, instance: Any, rel: Any):
        self.instance = instance
        self.through = rel.through

        self.source_field = self.through._model_meta.get_field(self.source_field_name)
        self.target_field = self.through._model_meta.get_field(self.target_field_name)

        self.core_filters = {}
        self.id_field_names = {}
        for lh_field, rh_field in self.source_field.related_fields:
            core_filter_key = f"{self.query_field_name}__{rh_field.name}"
            self.core_filters[core_filter_key] = getattr(instance, rh_field.attname)
            self.id_field_names[lh_field.name] = rh_field.name

        self.related_val = self.source_field.get_foreign_related_value(instance)
        if None in self.related_val:
            raise ValueError(
                f'"{instance!r}" needs to have a value for field "{self.id_field_names[self.source_field_name]}" before '
                "this many-to-many relationship can be used."
            )
        # Even if this relation is not to primary key, we require still primary key value.
        if instance.id is None:
            raise ValueError(
                f"{instance.__class__.__name__!r} instance needs to have a primary key value before "
                "a many-to-many relationship can be used."
            )

    def _apply_rel_filters(self, queryset: QuerySet) -> QuerySet:
        """Filter the queryset for the instance this manager is bound to."""
        queryset._defer_next_filter = True
        return queryset._next_is_sticky().filter(**self.core_filters)

    def _remove_prefetched_objects(self) -> None:
        try:
            self.instance._prefetched_objects_cache.pop(self.prefetch_cache_name)
        except (AttributeError, KeyError):
            pass  # nothing to clear from cache

    def get_queryset(self) -> QuerySet:
        try:
            return self.instance._prefetched_objects_cache[self.prefetch_cache_name]
        except (AttributeError, KeyError):
            queryset = self.model.query
            return self._apply_rel_filters(queryset)

    def get_prefetch_queryset(
        self, instances: Any, queryset: QuerySet | None = None
    ) -> tuple[QuerySet, Any, Any, bool, str, bool]:
        if queryset is None:
            queryset = self.model.query

        queryset = _filter_prefetch_queryset(
            queryset._next_is_sticky(), self.query_field_name, instances
        )

        # M2M: need to annotate the query in order to get the primary model
        # that the secondary model was actually related to.
        fk = self.through._model_meta.get_field(self.source_field_name)
        join_table = fk.model.model_options.db_table
        qn = db_connection.ops.quote_name
        queryset = queryset.extra(
            select={
                f"_prefetch_related_val_{f.attname}": f"{qn(join_table)}.{qn(f.column)}"
                for f in fk.local_related_fields
            }
        )
        return (
            queryset,
            lambda result: tuple(
                getattr(result, f"_prefetch_related_val_{f.attname}")
                for f in fk.local_related_fields
            ),
            lambda inst: tuple(
                f.get_db_prep_value(getattr(inst, f.attname), db_connection)
                for f in fk.foreign_related_fields
            ),
            False,
            self.prefetch_cache_name,
            False,
        )

    def clear(self) -> None:
        with transaction.atomic(savepoint=False):
            self._remove_prefetched_objects()
            filters = self._build_remove_filters(self.model.query)
            self.through.query.filter(filters).delete()

    def set(
        self,
        objs: Any,
        *,
        clear: bool = False,
        through_defaults: dict[str, Any] | None = None,
    ) -> None:
        # Force evaluation of `objs` in case it's a queryset whose value
        # could be affected by `manager.clear()`. Refs #19816.
        objs = tuple(objs)

        with transaction.atomic(savepoint=False):
            if clear:
                self.clear()
                self.add(*objs, through_defaults=through_defaults)
            else:
                old_ids = set(
                    self.query.values_list(
                        self.target_field.target_field.attname, flat=True
                    )
                )

                new_objs = []
                for obj in objs:
                    fk_val = (
                        self.target_field.get_foreign_related_value(obj)[0]
                        if isinstance(obj, self.model)
                        else self.target_field.get_prep_value(obj)
                    )
                    if fk_val in old_ids:
                        old_ids.remove(fk_val)
                    else:
                        new_objs.append(obj)

                self.remove(*old_ids)
                self.add(*new_objs, through_defaults=through_defaults)

    def create(
        self, *, through_defaults: dict[str, Any] | None = None, **kwargs: Any
    ) -> Any:
        new_obj = self.model.query.create(**kwargs)
        self.add(new_obj, through_defaults=through_defaults)
        return new_obj

    def get_or_create(
        self, *, through_defaults: dict[str, Any] | None = None, **kwargs: Any
    ) -> tuple[Any, bool]:
        obj, created = self.model.query.get_or_create(**kwargs)
        # We only need to add() if created because if we got an object back
        # from get() then the relationship already exists.
        if created:
            self.add(obj, through_defaults=through_defaults)
        return obj, created

    def update_or_create(
        self, *, through_defaults: dict[str, Any] | None = None, **kwargs: Any
    ) -> tuple[Any, bool]:
        obj, created = self.model.query.update_or_create(**kwargs)
        # We only need to add() if created because if we got an object back
        # from get() then the relationship already exists.
        if created:
            self.add(obj, through_defaults=through_defaults)
        return obj, created

    def _get_target_ids(self, target_field_name: str, objs: Any) -> set[Any]:
        """Return the set of ids of `objs` that the target field references."""
        from plain.models import Model

        target_ids = set()
        target_field = self.through._model_meta.get_field(target_field_name)
        for obj in objs:
            if isinstance(obj, self.model):
                target_id = target_field.get_foreign_related_value(obj)[0]
                if target_id is None:
                    raise ValueError(
                        f'Cannot add "{obj!r}": the value for field "{target_field_name}" is None'
                    )
                target_ids.add(target_id)
            elif isinstance(obj, Model):
                raise TypeError(
                    f"'{self.model.model_options.object_name}' instance expected, got {obj!r}"
                )
            else:
                target_ids.add(target_field.get_prep_value(obj))
        return target_ids

    def _get_missing_target_ids(
        self, source_field_name: str, target_field_name: str, target_ids: set[Any]
    ) -> set[Any]:
        """Return the subset of ids of `objs` that aren't already assigned to this relationship."""
        vals = self.through.query.values_list(target_field_name, flat=True).filter(
            **{
                source_field_name: self.related_val[0],
                f"{target_field_name}__in": target_ids,
            }
        )
        return target_ids.difference(vals)

    def _add_items(
        self,
        source_field_name: str,
        target_field_name: str,
        *objs: Any,
        through_defaults: dict[str, Any] | None = None,
    ) -> None:
        if not objs:
            return

        through_defaults = dict(resolve_callables(through_defaults or {}))
        target_ids = self._get_target_ids(target_field_name, objs)

        missing_target_ids = self._get_missing_target_ids(
            source_field_name, target_field_name, target_ids
        )
        with transaction.atomic(savepoint=False):
            # Add the ones that aren't there already.
            self.through.query.bulk_create(
                [
                    self.through(
                        **through_defaults,
                        **{
                            f"{source_field_name}_id": self.related_val[0],
                            f"{target_field_name}_id": target_id,
                        },
                    )
                    for target_id in missing_target_ids
                ],
            )

    def _remove_items(
        self, source_field_name: str, target_field_name: str, *objs: Any
    ) -> None:
        if not objs:
            return

        # Check that all the objects are of the right type
        old_ids = set()
        for obj in objs:
            if isinstance(obj, self.model):
                fk_val = self.target_field.get_foreign_related_value(obj)[0]
                old_ids.add(fk_val)
            else:
                old_ids.add(obj)

        with transaction.atomic(savepoint=False):
            target_model_qs = self.model.query
            if target_model_qs._has_filters():
                old_vals = target_model_qs.filter(
                    **{f"{self.target_field.target_field.attname}__in": old_ids}
                )
            else:
                old_vals = old_ids
            filters = self._build_remove_filters(old_vals)
            self.through.query.filter(filters).delete()

    # Subclasses must implement these methods:
    def _build_remove_filters(self, removed_vals: Any) -> Any:
        raise NotImplementedError

    def add(self, *objs: Any, through_defaults: dict[str, Any] | None = None) -> None:
        raise NotImplementedError

    def remove(self, *objs: Any) -> None:
        raise NotImplementedError


class ForwardManyToManyManager(BaseManyToManyManager):
    """
    Manager for the forward side of a many-to-many relation.

    This manager adds behaviors specific to many-to-many relations.
    """

    def __init__(self, instance: Any, rel: Any):
        # Set required attributes before calling super().__init__
        self.model = rel.model
        self.query_field_name = rel.field.related_query_name()
        self.prefetch_cache_name = rel.field.name
        self.source_field_name = rel.field.m2m_field_name()
        self.target_field_name = rel.field.m2m_reverse_field_name()
        self.symmetrical = rel.symmetrical

        super().__init__(instance, rel)

    def _build_remove_filters(self, removed_vals: Any) -> Any:
        filters = Q.create([(self.source_field_name, self.related_val)])
        # No need to add a subquery condition if removed_vals is a QuerySet without
        # filters.
        removed_vals_filters = (
            not isinstance(removed_vals, QuerySet) or removed_vals._has_filters()
        )
        if removed_vals_filters:
            filters = filters & Q.create(  # type: ignore[unsupported-operator]
                [(f"{self.target_field_name}__in", removed_vals)]
            )
        if self.symmetrical:
            symmetrical_filters = Q.create([(self.target_field_name, self.related_val)])
            if removed_vals_filters:
                symmetrical_filters = symmetrical_filters & Q.create(  # type: ignore[unsupported-operator]
                    [(f"{self.source_field_name}__in", removed_vals)]
                )
            filters = filters | symmetrical_filters  # type: ignore[unsupported-operator]
        return filters

    def add(self, *objs: Any, through_defaults: dict[str, Any] | None = None) -> None:
        self._remove_prefetched_objects()
        with transaction.atomic(savepoint=False):
            self._add_items(
                self.source_field_name,
                self.target_field_name,
                *objs,
                through_defaults=through_defaults,
            )
            # If this is a symmetrical m2m relation to self, add the mirror
            # entry in the m2m table.
            if self.symmetrical:
                self._add_items(
                    self.target_field_name,
                    self.source_field_name,
                    *objs,
                    through_defaults=through_defaults,
                )

    def remove(self, *objs: Any) -> None:
        self._remove_prefetched_objects()
        self._remove_items(self.source_field_name, self.target_field_name, *objs)


class ReverseManyToManyManager(BaseManyToManyManager):
    """
    Manager for the reverse side of a many-to-many relation.

    This manager adds behaviors specific to many-to-many relations.
    """

    def __init__(self, instance: Any, rel: Any):
        # Set required attributes before calling super().__init__
        self.model = rel.related_model
        self.query_field_name = rel.field.name
        self.prefetch_cache_name = rel.field.related_query_name()
        self.source_field_name = rel.field.m2m_reverse_field_name()
        self.target_field_name = rel.field.m2m_field_name()
        self.symmetrical = False  # Reverse relations are never symmetrical

        super().__init__(instance, rel)

    def _build_remove_filters(self, removed_vals: Any) -> Any:
        filters = Q.create([(self.source_field_name, self.related_val)])
        # No need to add a subquery condition if removed_vals is a QuerySet without
        # filters.
        removed_vals_filters = (
            not isinstance(removed_vals, QuerySet) or removed_vals._has_filters()
        )
        if removed_vals_filters:
            filters = filters & Q.create(  # type: ignore[unsupported-operator]
                [(f"{self.target_field_name}__in", removed_vals)]
            )
        # Note: reverse relations are never symmetrical, so no symmetrical logic here
        return filters

    def add(self, *objs: Any, through_defaults: dict[str, Any] | None = None) -> None:
        self._remove_prefetched_objects()
        with transaction.atomic(savepoint=False):
            self._add_items(
                self.source_field_name,
                self.target_field_name,
                *objs,
                through_defaults=through_defaults,
            )
            # Reverse relations are never symmetrical, so no mirror entry logic

    def remove(self, *objs: Any) -> None:
        self._remove_prefetched_objects()
        self._remove_items(self.source_field_name, self.target_field_name, *objs)
