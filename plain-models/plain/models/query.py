"""
The main QuerySet implementation. This provides the public API for the ORM.
"""

from __future__ import annotations

import copy
import operator
import warnings
from collections.abc import Callable, Iterator
from functools import cached_property
from itertools import chain, islice
from typing import TYPE_CHECKING, Any, Generic, Self, TypeVar

import plain.runtime
from plain.exceptions import ValidationError
from plain.models import (
    sql,
    transaction,
)
from plain.models.constants import LOOKUP_SEP, OnConflict
from plain.models.db import (
    PLAIN_VERSION_PICKLE_KEY,
    IntegrityError,
    NotSupportedError,
    db_connection,
)
from plain.models.exceptions import (
    FieldDoesNotExist,
    FieldError,
    ObjectDoesNotExist,
)
from plain.models.expressions import Case, F, Value, When
from plain.models.fields import (
    DateField,
    DateTimeField,
    Field,
    PrimaryKeyField,
)
from plain.models.functions import Cast, Trunc
from plain.models.query_utils import FilteredRelation, Q
from plain.models.sql.constants import CURSOR, GET_ITERATOR_CHUNK_SIZE
from plain.models.utils import (
    create_namedtuple_class,
    resolve_callables,
)
from plain.utils import timezone
from plain.utils.functional import partition

if TYPE_CHECKING:
    from datetime import tzinfo

    from plain.models import Model

# Type variable for QuerySet generic
T = TypeVar("T", bound="Model")

# The maximum number of results to fetch in a get() query.
MAX_GET_RESULTS = 21

# The maximum number of items to display in a QuerySet.__repr__
REPR_OUTPUT_SIZE = 20


class BaseIterable:
    def __init__(
        self,
        queryset: QuerySet[Any],
        chunked_fetch: bool = False,
        chunk_size: int = GET_ITERATOR_CHUNK_SIZE,
    ):
        self.queryset = queryset
        self.chunked_fetch = chunked_fetch
        self.chunk_size = chunk_size


class ModelIterable(BaseIterable):
    """Iterable that yields a model instance for each row."""

    def __iter__(self) -> Iterator[Model]:  # type: ignore[misc]
        queryset = self.queryset
        compiler = queryset.sql_query.get_compiler()
        # Execute the query. This will also fill compiler.select, klass_info,
        # and annotations.
        results = compiler.execute_sql(
            chunked_fetch=self.chunked_fetch, chunk_size=self.chunk_size
        )
        select, klass_info, annotation_col_map = (
            compiler.select,
            compiler.klass_info,
            compiler.annotation_col_map,
        )
        model_cls = klass_info["model"]
        select_fields = klass_info["select_fields"]
        model_fields_start, model_fields_end = select_fields[0], select_fields[-1] + 1
        init_list = [
            f[0].target.attname for f in select[model_fields_start:model_fields_end]
        ]
        related_populators = get_related_populators(klass_info, select)
        known_related_objects = [
            (
                field,
                related_objs,
                operator.attrgetter(field.attname),
            )
            for field, related_objs in queryset._known_related_objects.items()
        ]
        for row in compiler.results_iter(results):
            obj = model_cls.from_db(init_list, row[model_fields_start:model_fields_end])
            for rel_populator in related_populators:
                rel_populator.populate(row, obj)
            if annotation_col_map:
                for attr_name, col_pos in annotation_col_map.items():
                    setattr(obj, attr_name, row[col_pos])

            # Add the known related objects to the model.
            for field, rel_objs, rel_getter in known_related_objects:
                # Avoid overwriting objects loaded by, e.g., select_related().
                if field.is_cached(obj):
                    continue
                rel_obj_id = rel_getter(obj)
                try:
                    rel_obj = rel_objs[rel_obj_id]
                except KeyError:
                    pass  # May happen in qs1 | qs2 scenarios.
                else:
                    setattr(obj, field.name, rel_obj)

            yield obj


class RawModelIterable(BaseIterable):
    """
    Iterable that yields a model instance for each row from a raw queryset.
    """

    def __iter__(self) -> Iterator[Model]:  # type: ignore[misc]
        # Cache some things for performance reasons outside the loop.
        query = self.queryset.sql_query
        compiler = db_connection.ops.compiler("SQLCompiler")(query, db_connection)
        query_iterator = iter(query)

        try:
            (
                model_init_names,
                model_init_pos,
                annotation_fields,
            ) = self.queryset.resolve_model_init_order()
            model_cls = self.queryset.model
            if "id" not in model_init_names:
                raise FieldDoesNotExist("Raw query must include the primary key")
            fields = [self.queryset.model_fields.get(c) for c in self.queryset.columns]
            converters = compiler.get_converters(
                [
                    f.get_col(f.model.model_options.db_table) if f else None
                    for f in fields
                ]
            )
            if converters:
                query_iterator = compiler.apply_converters(query_iterator, converters)
            for values in query_iterator:
                # Associate fields to values
                model_init_values = [values[pos] for pos in model_init_pos]
                instance = model_cls.from_db(model_init_names, model_init_values)
                if annotation_fields:
                    for column, pos in annotation_fields:
                        setattr(instance, column, values[pos])
                yield instance
        finally:
            # Done iterating the Query. If it has its own cursor, close it.
            if hasattr(query, "cursor") and query.cursor:
                query.cursor.close()


class ValuesIterable(BaseIterable):
    """
    Iterable returned by QuerySet.values() that yields a dict for each row.
    """

    def __iter__(self) -> Iterator[dict[str, Any]]:  # type: ignore[misc]
        queryset = self.queryset
        query = queryset.sql_query
        compiler = query.get_compiler()

        # extra(select=...) cols are always at the start of the row.
        names = [
            *query.extra_select,
            *query.values_select,
            *query.annotation_select,
        ]
        indexes = range(len(names))
        for row in compiler.results_iter(
            chunked_fetch=self.chunked_fetch, chunk_size=self.chunk_size
        ):
            yield {names[i]: row[i] for i in indexes}


class ValuesListIterable(BaseIterable):
    """
    Iterable returned by QuerySet.values_list(flat=False) that yields a tuple
    for each row.
    """

    def __iter__(self) -> Iterator[tuple[Any, ...]]:  # type: ignore[misc]
        queryset = self.queryset
        query = queryset.sql_query
        compiler = query.get_compiler()

        if queryset._fields:
            # extra(select=...) cols are always at the start of the row.
            names = [
                *query.extra_select,
                *query.values_select,
                *query.annotation_select,
            ]
            fields = [
                *queryset._fields,
                *(f for f in query.annotation_select if f not in queryset._fields),
            ]
            if fields != names:
                # Reorder according to fields.
                index_map = {name: idx for idx, name in enumerate(names)}
                rowfactory = operator.itemgetter(*[index_map[f] for f in fields])
                return map(
                    rowfactory,
                    compiler.results_iter(
                        chunked_fetch=self.chunked_fetch, chunk_size=self.chunk_size
                    ),
                )
        return compiler.results_iter(
            tuple_expected=True,
            chunked_fetch=self.chunked_fetch,
            chunk_size=self.chunk_size,
        )


class NamedValuesListIterable(ValuesListIterable):
    """
    Iterable returned by QuerySet.values_list(named=True) that yields a
    namedtuple for each row.
    """

    def __iter__(self) -> Iterator[tuple[Any, ...]]:  # type: ignore[misc]
        queryset = self.queryset
        if queryset._fields:
            names = queryset._fields
        else:
            query = queryset.sql_query
            names = [
                *query.extra_select,
                *query.values_select,
                *query.annotation_select,
            ]
        tuple_class = create_namedtuple_class(*names)
        new = tuple.__new__
        for row in super().__iter__():
            yield new(tuple_class, row)


class FlatValuesListIterable(BaseIterable):
    """
    Iterable returned by QuerySet.values_list(flat=True) that yields single
    values.
    """

    def __iter__(self) -> Iterator[Any]:  # type: ignore[misc]
        queryset = self.queryset
        compiler = queryset.sql_query.get_compiler()
        for row in compiler.results_iter(
            chunked_fetch=self.chunked_fetch, chunk_size=self.chunk_size
        ):
            yield row[0]


class QuerySet(Generic[T]):
    """
    Represent a lazy database lookup for a set of objects.

    Usage:
        MyModel.query.filter(name="test").all()

    Custom QuerySets:
        from typing import Self

        class TaskQuerySet(QuerySet["Task"]):
            def active(self) -> Self:
                return self.filter(is_active=True)

        class Task(Model):
            is_active = BooleanField(default=True)
            query = TaskQuerySet()

        Task.query.active().filter(name="test")  # Full type inference

    Custom methods should return `Self` to preserve type through method chaining.
    """

    # Instance attributes (set in from_model())
    model: type[T]
    _query: sql.Query
    _result_cache: list[T] | None
    _sticky_filter: bool
    _for_write: bool
    _prefetch_related_lookups: tuple[Any, ...]
    _prefetch_done: bool
    _known_related_objects: dict[Any, dict[Any, Any]]
    _iterable_class: type[BaseIterable]
    _fields: tuple[str, ...] | None
    _defer_next_filter: bool
    _deferred_filter: tuple[bool, tuple[Any, ...], dict[str, Any]] | None

    def __init__(self):
        """Minimal init for descriptor mode. Use from_model() to create instances."""
        pass

    @classmethod
    def from_model(cls, model: type[T], query: sql.Query | None = None) -> Self:
        """Create a QuerySet instance bound to a model."""
        instance = cls()
        instance.model = model
        instance._query = query or sql.Query(model)
        instance._result_cache = None
        instance._sticky_filter = False
        instance._for_write = False
        instance._prefetch_related_lookups = ()
        instance._prefetch_done = False
        instance._known_related_objects = {}
        instance._iterable_class = ModelIterable
        instance._fields = None
        instance._defer_next_filter = False
        instance._deferred_filter = None
        return instance

    def __get__(self, instance: Any, owner: type[T]) -> Self:
        """Descriptor protocol - return a new QuerySet bound to the model."""
        if instance is not None:
            raise AttributeError(
                f"QuerySet is only accessible from the model class, not instances. "
                f"Use {owner.__name__}.query instead."
            )
        return self.from_model(owner)

    @property
    def sql_query(self) -> sql.Query:
        if self._deferred_filter:
            negate, args, kwargs = self._deferred_filter
            self._filter_or_exclude_inplace(negate, args, kwargs)
            self._deferred_filter = None
        return self._query

    @sql_query.setter
    def sql_query(self, value: sql.Query) -> None:
        if value.values_select:
            self._iterable_class = ValuesIterable
        self._query = value

    ########################
    # PYTHON MAGIC METHODS #
    ########################

    def __deepcopy__(self, memo: dict[int, Any]) -> QuerySet[T]:
        """Don't populate the QuerySet's cache."""
        obj = self.__class__.from_model(self.model)
        for k, v in self.__dict__.items():
            if k == "_result_cache":
                obj.__dict__[k] = None
            else:
                obj.__dict__[k] = copy.deepcopy(v, memo)
        return obj

    def __getstate__(self) -> dict[str, Any]:
        # Force the cache to be fully populated.
        self._fetch_all()
        return {**self.__dict__, PLAIN_VERSION_PICKLE_KEY: plain.runtime.__version__}

    def __setstate__(self, state: dict[str, Any]) -> None:
        pickled_version = state.get(PLAIN_VERSION_PICKLE_KEY)
        if pickled_version:
            if pickled_version != plain.runtime.__version__:
                warnings.warn(
                    f"Pickled queryset instance's Plain version {pickled_version} does not "
                    f"match the current version {plain.runtime.__version__}.",
                    RuntimeWarning,
                    stacklevel=2,
                )
        else:
            warnings.warn(
                "Pickled queryset instance's Plain version is not specified.",
                RuntimeWarning,
                stacklevel=2,
            )
        self.__dict__.update(state)

    def __repr__(self) -> str:
        data = list(self[: REPR_OUTPUT_SIZE + 1])
        if len(data) > REPR_OUTPUT_SIZE:
            data[-1] = "...(remaining elements truncated)..."
        return f"<{self.__class__.__name__} {data!r}>"

    def __len__(self) -> int:
        self._fetch_all()
        return len(self._result_cache)  # type: ignore[arg-type]

    def __iter__(self) -> Iterator[T]:
        """
        The queryset iterator protocol uses three nested iterators in the
        default case:
            1. sql.compiler.execute_sql()
               - Returns 100 rows at time (constants.GET_ITERATOR_CHUNK_SIZE)
                 using cursor.fetchmany(). This part is responsible for
                 doing some column masking, and returning the rows in chunks.
            2. sql.compiler.results_iter()
               - Returns one row at time. At this point the rows are still just
                 tuples. In some cases the return values are converted to
                 Python values at this location.
            3. self.iterator()
               - Responsible for turning the rows into model objects.
        """
        self._fetch_all()
        return iter(self._result_cache)  # type: ignore[arg-type]

    def __bool__(self) -> bool:
        self._fetch_all()
        return bool(self._result_cache)

    def __getitem__(self, k: int | slice) -> T | QuerySet[T]:
        """Retrieve an item or slice from the set of results."""
        if not isinstance(k, int | slice):
            raise TypeError(
                f"QuerySet indices must be integers or slices, not {type(k).__name__}."
            )
        if (isinstance(k, int) and k < 0) or (
            isinstance(k, slice)
            and (
                (k.start is not None and k.start < 0)
                or (k.stop is not None and k.stop < 0)
            )
        ):
            raise ValueError("Negative indexing is not supported.")

        if self._result_cache is not None:
            return self._result_cache[k]

        if isinstance(k, slice):
            qs = self._chain()
            if k.start is not None:
                start = int(k.start)
            else:
                start = None
            if k.stop is not None:
                stop = int(k.stop)
            else:
                stop = None
            qs.sql_query.set_limits(start, stop)
            return list(qs)[:: k.step] if k.step else qs  # type: ignore[return-value]

        qs = self._chain()
        qs.sql_query.set_limits(k, k + 1)  # type: ignore[unsupported-operator]
        qs._fetch_all()
        return qs._result_cache[0]

    def __class_getitem__(cls, *args: Any, **kwargs: Any) -> type[QuerySet[Any]]:
        return cls

    def __and__(self, other: QuerySet[T]) -> QuerySet[T]:
        self._check_operator_queryset(other, "&")
        self._merge_sanity_check(other)
        if isinstance(other, EmptyQuerySet):
            return other
        if isinstance(self, EmptyQuerySet):
            return self
        combined = self._chain()
        combined._merge_known_related_objects(other)
        combined.sql_query.combine(other.sql_query, sql.AND)
        return combined

    def __or__(self, other: QuerySet[T]) -> QuerySet[T]:
        self._check_operator_queryset(other, "|")
        self._merge_sanity_check(other)
        if isinstance(self, EmptyQuerySet):
            return other
        if isinstance(other, EmptyQuerySet):
            return self
        query = (
            self
            if self.sql_query.can_filter()
            else self.model._model_meta.base_queryset.filter(id__in=self.values("id"))
        )
        combined = query._chain()
        combined._merge_known_related_objects(other)
        if not other.sql_query.can_filter():
            other = other.model._model_meta.base_queryset.filter(
                id__in=other.values("id")
            )
        combined.sql_query.combine(other.sql_query, sql.OR)
        return combined

    def __xor__(self, other: QuerySet[T]) -> QuerySet[T]:
        self._check_operator_queryset(other, "^")
        self._merge_sanity_check(other)
        if isinstance(self, EmptyQuerySet):
            return other
        if isinstance(other, EmptyQuerySet):
            return self
        query = (
            self
            if self.sql_query.can_filter()
            else self.model._model_meta.base_queryset.filter(id__in=self.values("id"))
        )
        combined = query._chain()
        combined._merge_known_related_objects(other)
        if not other.sql_query.can_filter():
            other = other.model._model_meta.base_queryset.filter(
                id__in=other.values("id")
            )
        combined.sql_query.combine(other.sql_query, sql.XOR)
        return combined

    ####################################
    # METHODS THAT DO DATABASE QUERIES #
    ####################################

    def _iterator(self, use_chunked_fetch: bool, chunk_size: int | None) -> Iterator[T]:
        iterable = self._iterable_class(
            self,
            chunked_fetch=use_chunked_fetch,
            chunk_size=chunk_size or 2000,
        )
        if not self._prefetch_related_lookups or chunk_size is None:
            yield from iterable
            return

        iterator = iter(iterable)
        while results := list(islice(iterator, chunk_size)):
            prefetch_related_objects(results, *self._prefetch_related_lookups)
            yield from results

    def iterator(self, chunk_size: int | None = None) -> Iterator[T]:
        """
        An iterator over the results from applying this QuerySet to the
        database. chunk_size must be provided for QuerySets that prefetch
        related objects. Otherwise, a default chunk_size of 2000 is supplied.
        """
        if chunk_size is None:
            if self._prefetch_related_lookups:
                raise ValueError(
                    "chunk_size must be provided when using QuerySet.iterator() after "
                    "prefetch_related()."
                )
        elif chunk_size <= 0:
            raise ValueError("Chunk size must be strictly positive.")
        use_chunked_fetch = not db_connection.settings_dict.get(
            "DISABLE_SERVER_SIDE_CURSORS"
        )
        return self._iterator(use_chunked_fetch, chunk_size)

    def aggregate(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        """
        Return a dictionary containing the calculations (aggregation)
        over the current queryset.

        If args is present the expression is passed as a kwarg using
        the Aggregate object's default alias.
        """
        if self.sql_query.distinct_fields:
            raise NotImplementedError("aggregate() + distinct(fields) not implemented.")
        self._validate_values_are_expressions(
            (*args, *kwargs.values()), method_name="aggregate"
        )
        for arg in args:
            # The default_alias property raises TypeError if default_alias
            # can't be set automatically or AttributeError if it isn't an
            # attribute.
            try:
                arg.default_alias
            except (AttributeError, TypeError):
                raise TypeError("Complex aggregates require an alias")
            kwargs[arg.default_alias] = arg

        return self.sql_query.chain().get_aggregation(kwargs)

    def count(self) -> int:
        """
        Perform a SELECT COUNT() and return the number of records as an
        integer.

        If the QuerySet is already fully cached, return the length of the
        cached results set to avoid multiple SELECT COUNT(*) calls.
        """
        if self._result_cache is not None:
            return len(self._result_cache)

        return self.sql_query.get_count()

    def get(self, *args: Any, **kwargs: Any) -> T:
        """
        Perform the query and return a single object matching the given
        keyword arguments.
        """
        if self.sql_query.combinator and (args or kwargs):
            raise NotSupportedError(
                f"Calling QuerySet.get(...) with filters after {self.sql_query.combinator}() is not "
                "supported."
            )
        clone = (
            self._chain() if self.sql_query.combinator else self.filter(*args, **kwargs)
        )
        if self.sql_query.can_filter() and not self.sql_query.distinct_fields:
            clone = clone.order_by()
        limit = None
        if (
            not clone.sql_query.select_for_update
            or db_connection.features.supports_select_for_update_with_limit
        ):
            limit = MAX_GET_RESULTS
            clone.sql_query.set_limits(high=limit)
        num = len(clone)
        if num == 1:
            return clone._result_cache[0]
        if not num:
            raise self.model.DoesNotExist(
                f"{self.model.model_options.object_name} matching query does not exist."
            )
        raise self.model.MultipleObjectsReturned(
            "get() returned more than one {} -- it returned {}!".format(
                self.model.model_options.object_name,
                num if not limit or num < limit else "more than %s" % (limit - 1),
            )
        )

    def get_or_none(self, *args: Any, **kwargs: Any) -> T | None:
        """
        Perform the query and return a single object matching the given
        keyword arguments, or None if no object is found.
        """
        try:
            return self.get(*args, **kwargs)
        except self.model.DoesNotExist:  # type: ignore[attr-defined]
            return None

    def create(self, **kwargs: Any) -> T:
        """
        Create a new object with the given kwargs, saving it to the database
        and returning the created object.
        """
        obj = self.model(**kwargs)  # type: ignore[misc]
        self._for_write = True
        obj.save(force_insert=True)  # type: ignore[attr-defined]
        return obj

    def _prepare_for_bulk_create(self, objs: list[T]) -> None:
        id_field = self.model._model_meta.get_field("id")
        for obj in objs:
            if obj.id is None:  # type: ignore[attr-defined]
                # Populate new primary key values.
                obj.id = id_field.get_id_value_on_save(obj)  # type: ignore[attr-defined]
            obj._prepare_related_fields_for_save(operation_name="bulk_create")  # type: ignore[attr-defined]

    def _check_bulk_create_options(
        self,
        update_conflicts: bool,
        update_fields: list[Field] | None,
        unique_fields: list[Field] | None,
    ) -> OnConflict | None:
        db_features = db_connection.features
        if update_conflicts:
            if not db_features.supports_update_conflicts:
                raise NotSupportedError(
                    "This database backend does not support updating conflicts."
                )
            if not update_fields:
                raise ValueError(
                    "Fields that will be updated when a row insertion fails "
                    "on conflicts must be provided."
                )
            if unique_fields and not db_features.supports_update_conflicts_with_target:
                raise NotSupportedError(
                    "This database backend does not support updating "
                    "conflicts with specifying unique fields that can trigger "
                    "the upsert."
                )
            if not unique_fields and db_features.supports_update_conflicts_with_target:
                raise ValueError(
                    "Unique fields that can trigger the upsert must be provided."
                )
            # Updating primary keys and non-concrete fields is forbidden.
            if any(not f.concrete or f.many_to_many for f in update_fields):
                raise ValueError(
                    "bulk_create() can only be used with concrete fields in "
                    "update_fields."
                )
            if any(f.primary_key for f in update_fields):
                raise ValueError(
                    "bulk_create() cannot be used with primary keys in update_fields."
                )
            if unique_fields:
                if any(not f.concrete or f.many_to_many for f in unique_fields):
                    raise ValueError(
                        "bulk_create() can only be used with concrete fields "
                        "in unique_fields."
                    )
            return OnConflict.UPDATE
        return None

    def bulk_create(
        self,
        objs: list[T],
        batch_size: int | None = None,
        update_conflicts: bool = False,
        update_fields: list[str] | None = None,
        unique_fields: list[str] | None = None,
    ) -> list[T]:
        """
        Insert each of the instances into the database. Do *not* call
        save() on each of the instances, and do not set the primary key attribute if it is an
        autoincrement field (except if features.can_return_rows_from_bulk_insert=True).
        Multi-table models are not supported.
        """
        # When you bulk insert you don't get the primary keys back (if it's an
        # autoincrement, except if can_return_rows_from_bulk_insert=True), so
        # you can't insert into the child tables which references this. There
        # are two workarounds:
        # 1) This could be implemented if you didn't have an autoincrement pk
        # 2) You could do it by doing O(n) normal inserts into the parent
        #    tables to get the primary keys back and then doing a single bulk
        #    insert into the childmost table.
        # We currently set the primary keys on the objects when using
        # PostgreSQL via the RETURNING ID clause. It should be possible for
        # Oracle as well, but the semantics for extracting the primary keys is
        # trickier so it's not done yet.
        if batch_size is not None and batch_size <= 0:
            raise ValueError("Batch size must be a positive integer.")

        if not objs:
            return objs
        meta = self.model._model_meta
        if unique_fields:
            unique_fields = [meta.get_field(name) for name in unique_fields]
        if update_fields:
            update_fields = [meta.get_field(name) for name in update_fields]
        on_conflict = self._check_bulk_create_options(
            update_conflicts,
            update_fields,
            unique_fields,
        )
        self._for_write = True
        fields = meta.concrete_fields
        objs = list(objs)
        self._prepare_for_bulk_create(objs)
        with transaction.atomic(savepoint=False):
            objs_with_id, objs_without_id = partition(lambda o: o.id is None, objs)
            if objs_with_id:
                returned_columns = self._batched_insert(
                    objs_with_id,
                    fields,
                    batch_size,
                    on_conflict=on_conflict,
                    update_fields=update_fields,
                    unique_fields=unique_fields,
                )
                id_field = meta.get_field("id")
                for obj_with_id, results in zip(objs_with_id, returned_columns):
                    for result, field in zip(results, meta.db_returning_fields):
                        if field != id_field:
                            setattr(obj_with_id, field.attname, result)
                for obj_with_id in objs_with_id:
                    obj_with_id._state.adding = False
            if objs_without_id:
                fields = [f for f in fields if not isinstance(f, PrimaryKeyField)]
                returned_columns = self._batched_insert(
                    objs_without_id,
                    fields,
                    batch_size,
                    on_conflict=on_conflict,
                    update_fields=update_fields,
                    unique_fields=unique_fields,
                )
                if (
                    db_connection.features.can_return_rows_from_bulk_insert
                    and on_conflict is None
                ):
                    assert len(returned_columns) == len(objs_without_id)
                for obj_without_id, results in zip(objs_without_id, returned_columns):
                    for result, field in zip(results, meta.db_returning_fields):
                        setattr(obj_without_id, field.attname, result)
                    obj_without_id._state.adding = False

        return objs

    def bulk_update(
        self, objs: list[T], fields: list[str], batch_size: int | None = None
    ) -> int:
        """
        Update the given fields in each of the given objects in the database.
        """
        if batch_size is not None and batch_size <= 0:
            raise ValueError("Batch size must be a positive integer.")
        if not fields:
            raise ValueError("Field names must be given to bulk_update().")
        objs_tuple = tuple(objs)
        if any(obj.id is None for obj in objs_tuple):  # type: ignore[attr-defined]
            raise ValueError("All bulk_update() objects must have a primary key set.")
        fields_list = [self.model._model_meta.get_field(name) for name in fields]
        if any(not f.concrete or f.many_to_many for f in fields_list):
            raise ValueError("bulk_update() can only be used with concrete fields.")
        if any(f.primary_key for f in fields_list):
            raise ValueError("bulk_update() cannot be used with primary key fields.")
        if not objs_tuple:
            return 0
        for obj in objs_tuple:
            obj._prepare_related_fields_for_save(  # type: ignore[attr-defined]
                operation_name="bulk_update", fields=fields_list
            )
        # PK is used twice in the resulting update query, once in the filter
        # and once in the WHEN. Each field will also have one CAST.
        self._for_write = True
        max_batch_size = db_connection.ops.bulk_batch_size(
            ["id", "id"] + fields_list, objs_tuple
        )
        batch_size = min(batch_size, max_batch_size) if batch_size else max_batch_size
        requires_casting = db_connection.features.requires_casted_case_in_updates
        batches = (
            objs_tuple[i : i + batch_size]
            for i in range(0, len(objs_tuple), batch_size)
        )
        updates = []
        for batch_objs in batches:
            update_kwargs = {}
            for field in fields_list:
                when_statements = []
                for obj in batch_objs:
                    attr = getattr(obj, field.attname)
                    if not hasattr(attr, "resolve_expression"):
                        attr = Value(attr, output_field=field)
                    when_statements.append(When(id=obj.id, then=attr))  # type: ignore[attr-defined]
                case_statement = Case(*when_statements, output_field=field)
                if requires_casting:
                    case_statement = Cast(case_statement, output_field=field)
                update_kwargs[field.attname] = case_statement
            updates.append(([obj.id for obj in batch_objs], update_kwargs))  # type: ignore[attr-defined,misc]
        rows_updated = 0
        queryset = self._chain()
        with transaction.atomic(savepoint=False):
            for ids, update_kwargs in updates:
                rows_updated += queryset.filter(id__in=ids).update(**update_kwargs)
        return rows_updated

    def get_or_create(
        self, defaults: dict[str, Any] | None = None, **kwargs: Any
    ) -> tuple[T, bool]:
        """
        Look up an object with the given kwargs, creating one if necessary.
        Return a tuple of (object, created), where created is a boolean
        specifying whether an object was created.
        """
        # The get() needs to be targeted at the write database in order
        # to avoid potential transaction consistency problems.
        self._for_write = True
        try:
            return self.get(**kwargs), False
        except self.model.DoesNotExist:  # type: ignore[attr-defined]
            params = self._extract_model_params(defaults, **kwargs)
            # Try to create an object using passed params.
            try:
                with transaction.atomic():
                    params = dict(resolve_callables(params))
                    return self.create(**params), True
            except (IntegrityError, ValidationError):
                # Since create() also validates by default,
                # we can get any kind of ValidationError here,
                # or it can flow through and get an IntegrityError from the database.
                # The main thing we're concerned about is uniqueness failures,
                # but ValidationError could include other things too.
                # In all cases though it should be fine to try the get() again
                # and return an existing object.
                try:
                    return self.get(**kwargs), False
                except self.model.DoesNotExist:  # type: ignore[attr-defined]
                    pass
                raise

    def update_or_create(
        self,
        defaults: dict[str, Any] | None = None,
        create_defaults: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> tuple[T, bool]:
        """
        Look up an object with the given kwargs, updating one with defaults
        if it exists, otherwise create a new one. Optionally, an object can
        be created with different values than defaults by using
        create_defaults.
        Return a tuple (object, created), where created is a boolean
        specifying whether an object was created.
        """
        if create_defaults is None:
            update_defaults = create_defaults = defaults or {}
        else:
            update_defaults = defaults or {}
        self._for_write = True
        with transaction.atomic():
            # Lock the row so that a concurrent update is blocked until
            # update_or_create() has performed its save.
            obj, created = self.select_for_update().get_or_create(
                create_defaults, **kwargs
            )
            if created:
                return obj, created
            for k, v in resolve_callables(update_defaults):
                setattr(obj, k, v)

            update_fields = set(update_defaults)
            concrete_field_names = self.model._model_meta._non_pk_concrete_field_names
            # update_fields does not support non-concrete fields.
            if concrete_field_names.issuperset(update_fields):
                # Add fields which are set on pre_save(), e.g. auto_now fields.
                # This is to maintain backward compatibility as these fields
                # are not updated unless explicitly specified in the
                # update_fields list.
                for field in self.model._model_meta.local_concrete_fields:
                    if not (
                        field.primary_key or field.__class__.pre_save is Field.pre_save
                    ):
                        update_fields.add(field.name)
                        if field.name != field.attname:
                            update_fields.add(field.attname)
                obj.save(update_fields=update_fields)  # type: ignore[attr-defined]
            else:
                obj.save()  # type: ignore[attr-defined]
        return obj, False

    def _extract_model_params(
        self, defaults: dict[str, Any] | None, **kwargs: Any
    ) -> dict[str, Any]:
        """
        Prepare `params` for creating a model instance based on the given
        kwargs; for use by get_or_create().
        """
        defaults = defaults or {}
        params = {k: v for k, v in kwargs.items() if LOOKUP_SEP not in k}
        params.update(defaults)
        property_names = self.model._model_meta._property_names
        invalid_params = []
        for param in params:
            try:
                self.model._model_meta.get_field(param)
            except FieldDoesNotExist:
                # It's okay to use a model's property if it has a setter.
                if not (param in property_names and getattr(self.model, param).fset):
                    invalid_params.append(param)
        if invalid_params:
            raise FieldError(
                "Invalid field name(s) for model {}: '{}'.".format(
                    self.model.model_options.object_name,
                    "', '".join(sorted(invalid_params)),
                )
            )
        return params

    def first(self) -> T | None:
        """Return the first object of a query or None if no match is found."""
        for obj in self[:1]:
            return obj
        return None

    def last(self) -> T | None:
        """Return the last object of a query or None if no match is found."""
        queryset = self.reverse()
        for obj in queryset[:1]:
            return obj
        return None

    def in_bulk(
        self, id_list: list[Any] | None = None, *, field_name: str = "id"
    ) -> dict[Any, T]:
        """
        Return a dictionary mapping each of the given IDs to the object with
        that ID. If `id_list` isn't provided, evaluate the entire QuerySet.
        """
        if self.sql_query.is_sliced:
            raise TypeError("Cannot use 'limit' or 'offset' with in_bulk().")
        meta = self.model._model_meta
        unique_fields = [
            constraint.fields[0]
            for constraint in self.model.model_options.total_unique_constraints
            if len(constraint.fields) == 1
        ]
        if (
            field_name != "id"
            and not meta.get_field(field_name).primary_key
            and field_name not in unique_fields
            and self.sql_query.distinct_fields != (field_name,)
        ):
            raise ValueError(
                f"in_bulk()'s field_name must be a unique field but {field_name!r} isn't."
            )
        if id_list is not None:
            if not id_list:
                return {}
            filter_key = f"{field_name}__in"
            batch_size = db_connection.features.max_query_params
            id_list_tuple = tuple(id_list)
            # If the database has a limit on the number of query parameters
            # (e.g. SQLite), retrieve objects in batches if necessary.
            if batch_size and batch_size < len(id_list_tuple):
                qs: tuple[T, ...] = ()
                for offset in range(0, len(id_list_tuple), batch_size):
                    batch = id_list_tuple[offset : offset + batch_size]
                    qs += tuple(self.filter(**{filter_key: batch}))
            else:
                qs = self.filter(**{filter_key: id_list_tuple})
        else:
            qs = self._chain()
        return {getattr(obj, field_name): obj for obj in qs}

    def delete(self) -> tuple[int, dict[str, int]]:
        """Delete the records in the current QuerySet."""
        self._not_support_combined_queries("delete")
        if self.sql_query.is_sliced:
            raise TypeError("Cannot use 'limit' or 'offset' with delete().")
        if self.sql_query.distinct or self.sql_query.distinct_fields:
            raise TypeError("Cannot call delete() after .distinct().")
        if self._fields is not None:
            raise TypeError("Cannot call delete() after .values() or .values_list()")

        del_query = self._chain()

        # The delete is actually 2 queries - one to find related objects,
        # and one to delete. Make sure that the discovery of related
        # objects is performed on the same database as the deletion.
        del_query._for_write = True

        # Disable non-supported fields.
        del_query.sql_query.select_for_update = False
        del_query.sql_query.select_related = False
        del_query.sql_query.clear_ordering(force=True)

        from plain.models.deletion import Collector

        collector = Collector(origin=self)
        collector.collect(del_query)
        deleted, _rows_count = collector.delete()

        # Clear the result cache, in case this QuerySet gets reused.
        self._result_cache = None
        return deleted, _rows_count

    def _raw_delete(self) -> int:
        """
        Delete objects found from the given queryset in single direct SQL
        query. No signals are sent and there is no protection for cascades.
        """
        query = self.sql_query.clone()
        query.__class__ = sql.DeleteQuery
        cursor = query.get_compiler().execute_sql(CURSOR)
        if cursor:
            with cursor:
                return cursor.rowcount
        return 0

    def update(self, **kwargs: Any) -> int:
        """
        Update all elements in the current QuerySet, setting all the given
        fields to the appropriate values.
        """
        self._not_support_combined_queries("update")
        if self.sql_query.is_sliced:
            raise TypeError("Cannot update a query once a slice has been taken.")
        self._for_write = True
        query = self.sql_query.chain(sql.UpdateQuery)
        query.add_update_values(kwargs)

        # Inline annotations in order_by(), if possible.
        new_order_by = []
        for col in query.order_by:
            alias = col
            descending = False
            if isinstance(alias, str) and alias.startswith("-"):
                alias = alias.removeprefix("-")
                descending = True
            if annotation := query.annotations.get(alias):
                if getattr(annotation, "contains_aggregate", False):
                    raise FieldError(
                        f"Cannot update when ordering by an aggregate: {annotation}"
                    )
                if descending:
                    annotation = annotation.desc()
                new_order_by.append(annotation)
            else:
                new_order_by.append(col)
        query.order_by = tuple(new_order_by)

        # Clear any annotations so that they won't be present in subqueries.
        query.annotations = {}
        with transaction.mark_for_rollback_on_error():
            rows = query.get_compiler().execute_sql(CURSOR)
        self._result_cache = None
        return rows

    def _update(self, values: list[tuple[Field, Any, Any]]) -> int:
        """
        A version of update() that accepts field objects instead of field names.
        Used primarily for model saving and not intended for use by general
        code (it requires too much poking around at model internals to be
        useful at that level).
        """
        if self.sql_query.is_sliced:
            raise TypeError("Cannot update a query once a slice has been taken.")
        query = self.sql_query.chain(sql.UpdateQuery)
        query.add_update_fields(values)
        # Clear any annotations so that they won't be present in subqueries.
        query.annotations = {}
        self._result_cache = None
        return query.get_compiler().execute_sql(CURSOR)

    def exists(self) -> bool:
        """
        Return True if the QuerySet would have any results, False otherwise.
        """
        if self._result_cache is None:
            return self.sql_query.has_results()
        return bool(self._result_cache)

    def contains(self, obj: T) -> bool:
        """
        Return True if the QuerySet contains the provided obj,
        False otherwise.
        """
        self._not_support_combined_queries("contains")
        if self._fields is not None:
            raise TypeError(
                "Cannot call QuerySet.contains() after .values() or .values_list()."
            )
        try:
            if obj.__class__ != self.model:
                return False
        except AttributeError:
            raise TypeError("'obj' must be a model instance.")
        if obj.id is None:  # type: ignore[attr-defined]
            raise ValueError("QuerySet.contains() cannot be used on unsaved objects.")
        if self._result_cache is not None:
            return obj in self._result_cache
        return self.filter(id=obj.id).exists()  # type: ignore[attr-defined]

    def _prefetch_related_objects(self) -> None:
        # This method can only be called once the result cache has been filled.
        prefetch_related_objects(self._result_cache, *self._prefetch_related_lookups)
        self._prefetch_done = True

    def explain(self, *, format: str | None = None, **options: Any) -> str:
        """
        Runs an EXPLAIN on the SQL query this QuerySet would perform, and
        returns the results.
        """
        return self.sql_query.explain(format=format, **options)

    ##################################################
    # PUBLIC METHODS THAT RETURN A QUERYSET SUBCLASS #
    ##################################################

    def raw(
        self,
        raw_query: str,
        params: tuple[Any, ...] = (),
        translations: dict[str, str] | None = None,
    ) -> RawQuerySet:
        qs = RawQuerySet(
            raw_query,
            model=self.model,
            params=params,
            translations=translations,
        )
        qs._prefetch_related_lookups = self._prefetch_related_lookups[:]
        return qs

    def _values(self, *fields: str, **expressions: Any) -> QuerySet[Any]:
        clone = self._chain()
        if expressions:
            clone = clone.annotate(**expressions)
        clone._fields = fields  # type: ignore[assignment]
        clone.sql_query.set_values(fields)
        return clone

    def values(self, *fields: str, **expressions: Any) -> QuerySet[Any]:
        fields += tuple(expressions)
        clone = self._values(*fields, **expressions)
        clone._iterable_class = ValuesIterable
        return clone

    def values_list(
        self, *fields: str, flat: bool = False, named: bool = False
    ) -> QuerySet[Any]:
        if flat and named:
            raise TypeError("'flat' and 'named' can't be used together.")
        if flat and len(fields) > 1:
            raise TypeError(
                "'flat' is not valid when values_list is called with more than one "
                "field."
            )

        field_names = {f for f in fields if not hasattr(f, "resolve_expression")}
        _fields = []
        expressions = {}
        counter = 1
        for field in fields:
            if hasattr(field, "resolve_expression"):
                field_id_prefix = getattr(
                    field, "default_alias", field.__class__.__name__.lower()
                )
                while True:
                    field_id = field_id_prefix + str(counter)
                    counter += 1
                    if field_id not in field_names:
                        break
                expressions[field_id] = field
                _fields.append(field_id)
            else:
                _fields.append(field)

        clone = self._values(*_fields, **expressions)
        clone._iterable_class = (
            NamedValuesListIterable
            if named
            else FlatValuesListIterable
            if flat
            else ValuesListIterable
        )
        return clone

    def dates(self, field_name: str, kind: str, order: str = "ASC") -> QuerySet[Any]:
        """
        Return a list of date objects representing all available dates for
        the given field_name, scoped to 'kind'.
        """
        if kind not in ("year", "month", "week", "day"):
            raise ValueError("'kind' must be one of 'year', 'month', 'week', or 'day'.")
        if order not in ("ASC", "DESC"):
            raise ValueError("'order' must be either 'ASC' or 'DESC'.")
        return (
            self.annotate(
                datefield=Trunc(field_name, kind, output_field=DateField()),
                plain_field=F(field_name),
            )
            .values_list("datefield", flat=True)
            .distinct()
            .filter(plain_field__isnull=False)
            .order_by(("-" if order == "DESC" else "") + "datefield")
        )

    def datetimes(
        self,
        field_name: str,
        kind: str,
        order: str = "ASC",
        tzinfo: tzinfo | None = None,
    ) -> QuerySet[Any]:
        """
        Return a list of datetime objects representing all available
        datetimes for the given field_name, scoped to 'kind'.
        """
        if kind not in ("year", "month", "week", "day", "hour", "minute", "second"):
            raise ValueError(
                "'kind' must be one of 'year', 'month', 'week', 'day', "
                "'hour', 'minute', or 'second'."
            )
        if order not in ("ASC", "DESC"):
            raise ValueError("'order' must be either 'ASC' or 'DESC'.")

        if tzinfo is None:
            tzinfo = timezone.get_current_timezone()

        return (
            self.annotate(
                datetimefield=Trunc(
                    field_name,
                    kind,
                    output_field=DateTimeField(),
                    tzinfo=tzinfo,
                ),
                plain_field=F(field_name),
            )
            .values_list("datetimefield", flat=True)
            .distinct()
            .filter(plain_field__isnull=False)
            .order_by(("-" if order == "DESC" else "") + "datetimefield")
        )

    def none(self) -> QuerySet[T]:
        """Return an empty QuerySet."""
        clone = self._chain()
        clone.sql_query.set_empty()
        return clone

    ##################################################################
    # PUBLIC METHODS THAT ALTER ATTRIBUTES AND RETURN A NEW QUERYSET #
    ##################################################################

    def all(self) -> Self:
        """
        Return a new QuerySet that is a copy of the current one. This allows a
        QuerySet to proxy for a model queryset in some cases.
        """
        return self._chain()

    def filter(self, *args: Any, **kwargs: Any) -> Self:
        """
        Return a new QuerySet instance with the args ANDed to the existing
        set.
        """
        self._not_support_combined_queries("filter")
        return self._filter_or_exclude(False, args, kwargs)

    def exclude(self, *args: Any, **kwargs: Any) -> Self:
        """
        Return a new QuerySet instance with NOT (args) ANDed to the existing
        set.
        """
        self._not_support_combined_queries("exclude")
        return self._filter_or_exclude(True, args, kwargs)

    def _filter_or_exclude(
        self, negate: bool, args: tuple[Any, ...], kwargs: dict[str, Any]
    ) -> Self:
        if (args or kwargs) and self.sql_query.is_sliced:
            raise TypeError("Cannot filter a query once a slice has been taken.")
        clone = self._chain()
        if self._defer_next_filter:
            self._defer_next_filter = False
            clone._deferred_filter = negate, args, kwargs
        else:
            clone._filter_or_exclude_inplace(negate, args, kwargs)
        return clone

    def _filter_or_exclude_inplace(
        self, negate: bool, args: tuple[Any, ...], kwargs: dict[str, Any]
    ) -> None:
        if negate:
            self._query.add_q(~Q(*args, **kwargs))  # type: ignore[unsupported-operator]
        else:
            self._query.add_q(Q(*args, **kwargs))

    def complex_filter(self, filter_obj: Q | dict[str, Any]) -> QuerySet[T]:
        """
        Return a new QuerySet instance with filter_obj added to the filters.

        filter_obj can be a Q object or a dictionary of keyword lookup
        arguments.

        This exists to support framework features such as 'limit_choices_to',
        and usually it will be more natural to use other methods.
        """
        if isinstance(filter_obj, Q):
            clone = self._chain()
            clone.sql_query.add_q(filter_obj)
            return clone
        else:
            return self._filter_or_exclude(False, args=(), kwargs=filter_obj)

    def _combinator_query(
        self, combinator: str, *other_qs: QuerySet[T], all: bool = False
    ) -> QuerySet[T]:
        # Clone the query to inherit the select list and everything
        clone = self._chain()
        # Clear limits and ordering so they can be reapplied
        clone.sql_query.clear_ordering(force=True)
        clone.sql_query.clear_limits()
        clone.sql_query.combined_queries = (self.sql_query,) + tuple(
            qs.sql_query for qs in other_qs
        )
        clone.sql_query.combinator = combinator
        clone.sql_query.combinator_all = all
        return clone

    def union(self, *other_qs: QuerySet[T], all: bool = False) -> QuerySet[T]:
        # If the query is an EmptyQuerySet, combine all nonempty querysets.
        if isinstance(self, EmptyQuerySet):
            qs = [q for q in other_qs if not isinstance(q, EmptyQuerySet)]
            if not qs:
                return self
            if len(qs) == 1:
                return qs[0]
            return qs[0]._combinator_query("union", *qs[1:], all=all)
        return self._combinator_query("union", *other_qs, all=all)

    def intersection(self, *other_qs: QuerySet[T]) -> QuerySet[T]:
        # If any query is an EmptyQuerySet, return it.
        if isinstance(self, EmptyQuerySet):
            return self
        for other in other_qs:
            if isinstance(other, EmptyQuerySet):
                return other
        return self._combinator_query("intersection", *other_qs)

    def difference(self, *other_qs: QuerySet[T]) -> QuerySet[T]:
        # If the query is an EmptyQuerySet, return it.
        if isinstance(self, EmptyQuerySet):
            return self
        return self._combinator_query("difference", *other_qs)

    def select_for_update(
        self,
        nowait: bool = False,
        skip_locked: bool = False,
        of: tuple[str, ...] = (),
        no_key: bool = False,
    ) -> QuerySet[T]:
        """
        Return a new QuerySet instance that will select objects with a
        FOR UPDATE lock.
        """
        if nowait and skip_locked:
            raise ValueError("The nowait option cannot be used with skip_locked.")
        obj = self._chain()
        obj._for_write = True
        obj.sql_query.select_for_update = True
        obj.sql_query.select_for_update_nowait = nowait
        obj.sql_query.select_for_update_skip_locked = skip_locked
        obj.sql_query.select_for_update_of = of
        obj.sql_query.select_for_no_key_update = no_key
        return obj

    def select_related(self, *fields: str | None) -> Self:
        """
        Return a new QuerySet instance that will select related objects.

        If fields are specified, they must be ForeignKey fields and only those
        related objects are included in the selection.

        If select_related(None) is called, clear the list.
        """
        self._not_support_combined_queries("select_related")
        if self._fields is not None:
            raise TypeError(
                "Cannot call select_related() after .values() or .values_list()"
            )

        obj = self._chain()
        if fields == (None,):
            obj.sql_query.select_related = False
        elif fields:
            obj.sql_query.add_select_related(fields)
        else:
            obj.sql_query.select_related = True
        return obj

    def prefetch_related(self, *lookups: str | Prefetch | None) -> Self:
        """
        Return a new QuerySet instance that will prefetch the specified
        Many-To-One and Many-To-Many related objects when the QuerySet is
        evaluated.

        When prefetch_related() is called more than once, append to the list of
        prefetch lookups. If prefetch_related(None) is called, clear the list.
        """
        self._not_support_combined_queries("prefetch_related")
        clone = self._chain()
        if lookups == (None,):
            clone._prefetch_related_lookups = ()
        else:
            for lookup in lookups:
                lookup_str: str
                if isinstance(lookup, Prefetch):
                    lookup_str = lookup.prefetch_to
                else:
                    lookup_str = lookup  # type: ignore[assignment]
                lookup_str = lookup_str.split(LOOKUP_SEP, 1)[0]
                if lookup_str in self.sql_query._filtered_relations:
                    raise ValueError(
                        "prefetch_related() is not supported with FilteredRelation."
                    )
            clone._prefetch_related_lookups = clone._prefetch_related_lookups + lookups
        return clone

    def annotate(self, *args: Any, **kwargs: Any) -> Self:
        """
        Return a query set in which the returned objects have been annotated
        with extra data or aggregations.
        """
        self._not_support_combined_queries("annotate")
        return self._annotate(args, kwargs, select=True)

    def alias(self, *args: Any, **kwargs: Any) -> Self:
        """
        Return a query set with added aliases for extra data or aggregations.
        """
        self._not_support_combined_queries("alias")
        return self._annotate(args, kwargs, select=False)

    def _annotate(
        self, args: tuple[Any, ...], kwargs: dict[str, Any], select: bool = True
    ) -> Self:
        self._validate_values_are_expressions(
            args + tuple(kwargs.values()), method_name="annotate"
        )
        annotations = {}
        for arg in args:
            # The default_alias property may raise a TypeError.
            try:
                if arg.default_alias in kwargs:
                    raise ValueError(
                        f"The named annotation '{arg.default_alias}' conflicts with the "
                        "default name for another annotation."
                    )
            except TypeError:
                raise TypeError("Complex annotations require an alias")
            annotations[arg.default_alias] = arg
        annotations.update(kwargs)

        clone = self._chain()
        names = self._fields
        if names is None:
            names = set(
                chain.from_iterable(
                    (field.name, field.attname)
                    if hasattr(field, "attname")
                    else (field.name,)
                    for field in self.model._model_meta.get_fields()
                )
            )

        for alias, annotation in annotations.items():
            if alias in names:
                raise ValueError(
                    f"The annotation '{alias}' conflicts with a field on the model."
                )
            if isinstance(annotation, FilteredRelation):
                clone.sql_query.add_filtered_relation(annotation, alias)
            else:
                clone.sql_query.add_annotation(
                    annotation,
                    alias,
                    select=select,
                )
        for alias, annotation in clone.sql_query.annotations.items():
            if alias in annotations and annotation.contains_aggregate:
                if clone._fields is None:
                    clone.sql_query.group_by = True
                else:
                    clone.sql_query.set_group_by()
                break

        return clone

    def order_by(self, *field_names: str) -> Self:
        """Return a new QuerySet instance with the ordering changed."""
        if self.sql_query.is_sliced:
            raise TypeError("Cannot reorder a query once a slice has been taken.")
        obj = self._chain()
        obj.sql_query.clear_ordering(force=True, clear_default=False)
        obj.sql_query.add_ordering(*field_names)
        return obj

    def distinct(self, *field_names: str) -> Self:
        """
        Return a new QuerySet instance that will select only distinct results.
        """
        self._not_support_combined_queries("distinct")
        if self.sql_query.is_sliced:
            raise TypeError(
                "Cannot create distinct fields once a slice has been taken."
            )
        obj = self._chain()
        obj.sql_query.add_distinct_fields(*field_names)
        return obj

    def extra(
        self,
        select: dict[str, str] | None = None,
        where: list[str] | None = None,
        params: list[Any] | None = None,
        tables: list[str] | None = None,
        order_by: list[str] | None = None,
        select_params: list[Any] | None = None,
    ) -> QuerySet[T]:
        """Add extra SQL fragments to the query."""
        self._not_support_combined_queries("extra")
        if self.sql_query.is_sliced:
            raise TypeError("Cannot change a query once a slice has been taken.")
        clone = self._chain()
        clone.sql_query.add_extra(
            select, select_params, where, params, tables, order_by
        )
        return clone

    def reverse(self) -> QuerySet[T]:
        """Reverse the ordering of the QuerySet."""
        if self.sql_query.is_sliced:
            raise TypeError("Cannot reverse a query once a slice has been taken.")
        clone = self._chain()
        clone.sql_query.standard_ordering = not clone.sql_query.standard_ordering
        return clone

    def defer(self, *fields: str | None) -> QuerySet[T]:
        """
        Defer the loading of data for certain fields until they are accessed.
        Add the set of deferred fields to any existing set of deferred fields.
        The only exception to this is if None is passed in as the only
        parameter, in which case removal all deferrals.
        """
        self._not_support_combined_queries("defer")
        if self._fields is not None:
            raise TypeError("Cannot call defer() after .values() or .values_list()")
        clone = self._chain()
        if fields == (None,):
            clone.sql_query.clear_deferred_loading()
        else:
            clone.sql_query.add_deferred_loading(fields)
        return clone

    def only(self, *fields: str) -> QuerySet[T]:
        """
        Essentially, the opposite of defer(). Only the fields passed into this
        method and that are not already specified as deferred are loaded
        immediately when the queryset is evaluated.
        """
        self._not_support_combined_queries("only")
        if self._fields is not None:
            raise TypeError("Cannot call only() after .values() or .values_list()")
        if fields == (None,):
            # Can only pass None to defer(), not only(), as the rest option.
            # That won't stop people trying to do this, so let's be explicit.
            raise TypeError("Cannot pass None as an argument to only().")
        for field in fields:
            field = field.split(LOOKUP_SEP, 1)[0]
            if field in self.sql_query._filtered_relations:
                raise ValueError("only() is not supported with FilteredRelation.")
        clone = self._chain()
        clone.sql_query.add_immediate_loading(fields)
        return clone

    ###################################
    # PUBLIC INTROSPECTION ATTRIBUTES #
    ###################################

    @property
    def ordered(self) -> bool:
        """
        Return True if the QuerySet is ordered -- i.e. has an order_by()
        clause or a default ordering on the model (or is empty).
        """
        if isinstance(self, EmptyQuerySet):
            return True
        if self.sql_query.extra_order_by or self.sql_query.order_by:
            return True
        elif (
            self.sql_query.default_ordering
            and self.sql_query.get_model_meta().ordering
            and
            # A default ordering doesn't affect GROUP BY queries.
            not self.sql_query.group_by
        ):
            return True
        else:
            return False

    ###################
    # PRIVATE METHODS #
    ###################

    def _insert(
        self,
        objs: list[T],
        fields: list[Field],
        returning_fields: list[Field] | None = None,
        raw: bool = False,
        on_conflict: OnConflict | None = None,
        update_fields: list[Field] | None = None,
        unique_fields: list[Field] | None = None,
    ) -> list[tuple[Any, ...]] | None:
        """
        Insert a new record for the given model. This provides an interface to
        the InsertQuery class and is how Model.save() is implemented.
        """
        self._for_write = True
        query = sql.InsertQuery(
            self.model,
            on_conflict=on_conflict.value if on_conflict else None,  # type: ignore[attr-defined]
            update_fields=update_fields,
            unique_fields=unique_fields,
        )
        query.insert_values(fields, objs, raw=raw)
        return query.get_compiler().execute_sql(returning_fields)

    def _batched_insert(
        self,
        objs: list[T],
        fields: list[Field],
        batch_size: int,
        on_conflict: OnConflict | None = None,
        update_fields: list[Field] | None = None,
        unique_fields: list[Field] | None = None,
    ) -> list[tuple[Any, ...]]:
        """
        Helper method for bulk_create() to insert objs one batch at a time.
        """
        ops = db_connection.ops
        max_batch_size = max(ops.bulk_batch_size(fields, objs), 1)
        batch_size = min(batch_size, max_batch_size) if batch_size else max_batch_size
        inserted_rows = []
        bulk_return = db_connection.features.can_return_rows_from_bulk_insert
        for item in [objs[i : i + batch_size] for i in range(0, len(objs), batch_size)]:
            if bulk_return and on_conflict is None:
                inserted_rows.extend(
                    self._insert(
                        item,
                        fields=fields,
                        returning_fields=self.model._model_meta.db_returning_fields,
                    )
                )
            else:
                self._insert(
                    item,
                    fields=fields,
                    on_conflict=on_conflict,
                    update_fields=update_fields,
                    unique_fields=unique_fields,
                )
        return inserted_rows

    def _chain(self) -> Self:
        """
        Return a copy of the current QuerySet that's ready for another
        operation.
        """
        obj = self._clone()
        if obj._sticky_filter:
            obj.sql_query.filter_is_sticky = True
            obj._sticky_filter = False
        return obj

    def _clone(self) -> Self:
        """
        Return a copy of the current QuerySet. A lightweight alternative
        to deepcopy().
        """
        c = self.__class__.from_model(
            model=self.model,
            query=self.sql_query.chain(),
        )
        c._sticky_filter = self._sticky_filter
        c._for_write = self._for_write
        c._prefetch_related_lookups = self._prefetch_related_lookups[:]
        c._known_related_objects = self._known_related_objects
        c._iterable_class = self._iterable_class
        c._fields = self._fields
        return c

    def _fetch_all(self) -> None:
        if self._result_cache is None:
            self._result_cache = list(self._iterable_class(self))
        if self._prefetch_related_lookups and not self._prefetch_done:
            self._prefetch_related_objects()

    def _next_is_sticky(self) -> QuerySet[T]:
        """
        Indicate that the next filter call and the one following that should
        be treated as a single filter. This is only important when it comes to
        determining when to reuse tables for many-to-many filters. Required so
        that we can filter naturally on the results of related managers.

        This doesn't return a clone of the current QuerySet (it returns
        "self"). The method is only used internally and should be immediately
        followed by a filter() that does create a clone.
        """
        self._sticky_filter = True
        return self

    def _merge_sanity_check(self, other: QuerySet[T]) -> None:
        """Check that two QuerySet classes may be merged."""
        if self._fields is not None and (
            set(self.sql_query.values_select) != set(other.sql_query.values_select)
            or set(self.sql_query.extra_select) != set(other.sql_query.extra_select)
            or set(self.sql_query.annotation_select)
            != set(other.sql_query.annotation_select)
        ):
            raise TypeError(
                f"Merging '{self.__class__.__name__}' classes must involve the same values in each case."
            )

    def _merge_known_related_objects(self, other: QuerySet[T]) -> None:
        """
        Keep track of all known related objects from either QuerySet instance.
        """
        for field, objects in other._known_related_objects.items():
            self._known_related_objects.setdefault(field, {}).update(objects)

    def resolve_expression(self, *args: Any, **kwargs: Any) -> sql.Query:
        if self._fields and len(self._fields) > 1:
            # values() queryset can only be used as nested queries
            # if they are set up to select only a single field.
            raise TypeError("Cannot use multi-field values as a filter value.")
        query = self.sql_query.resolve_expression(*args, **kwargs)
        return query

    def _has_filters(self) -> bool:
        """
        Check if this QuerySet has any filtering going on. This isn't
        equivalent with checking if all objects are present in results, for
        example, qs[1:]._has_filters() -> False.
        """
        return self.sql_query.has_filters()

    @staticmethod
    def _validate_values_are_expressions(
        values: tuple[Any, ...], method_name: str
    ) -> None:
        invalid_args = sorted(
            str(arg) for arg in values if not hasattr(arg, "resolve_expression")
        )
        if invalid_args:
            raise TypeError(
                "QuerySet.{}() received non-expression(s): {}.".format(
                    method_name,
                    ", ".join(invalid_args),
                )
            )

    def _not_support_combined_queries(self, operation_name: str) -> None:
        if self.sql_query.combinator:
            raise NotSupportedError(
                f"Calling QuerySet.{operation_name}() after {self.sql_query.combinator}() is not supported."
            )

    def _check_operator_queryset(self, other: QuerySet[T], operator_: str) -> None:
        if self.sql_query.combinator or other.sql_query.combinator:
            raise TypeError(f"Cannot use {operator_} operator with combined queryset.")


class InstanceCheckMeta(type):
    def __instancecheck__(self, instance: object) -> bool:
        return isinstance(instance, QuerySet) and instance.sql_query.is_empty()


class EmptyQuerySet(metaclass=InstanceCheckMeta):
    """
    Marker class to checking if a queryset is empty by .none():
        isinstance(qs.none(), EmptyQuerySet) -> True
    """

    def __init__(self, *args: Any, **kwargs: Any):
        raise TypeError("EmptyQuerySet can't be instantiated")


class RawQuerySet:
    """
    Provide an iterator which converts the results of raw SQL queries into
    annotated model instances.
    """

    def __init__(
        self,
        raw_query: str,
        model: type[Model] | None = None,
        query: sql.RawQuery | None = None,
        params: tuple[Any, ...] = (),
        translations: dict[str, str] | None = None,
    ):
        self.raw_query = raw_query
        self.model = model
        self.sql_query = query or sql.RawQuery(sql=raw_query, params=params)
        self.params = params
        self.translations = translations or {}
        self._result_cache: list[Model] | None = None
        self._prefetch_related_lookups: tuple[Any, ...] = ()
        self._prefetch_done = False

    def resolve_model_init_order(
        self,
    ) -> tuple[list[str], list[int], list[tuple[str, int]]]:
        """Resolve the init field names and value positions."""
        converter = db_connection.introspection.identifier_converter
        model_init_fields = [
            f
            for f in self.model._model_meta.fields
            if converter(f.column) in self.columns
        ]
        annotation_fields = [
            (column, pos)
            for pos, column in enumerate(self.columns)
            if column not in self.model_fields
        ]
        model_init_order = [
            self.columns.index(converter(f.column)) for f in model_init_fields
        ]
        model_init_names = [f.attname for f in model_init_fields]
        return model_init_names, model_init_order, annotation_fields

    def prefetch_related(self, *lookups: str | Prefetch | None) -> RawQuerySet:
        """Same as QuerySet.prefetch_related()"""
        clone = self._clone()
        if lookups == (None,):
            clone._prefetch_related_lookups = ()
        else:
            clone._prefetch_related_lookups = clone._prefetch_related_lookups + lookups
        return clone

    def _prefetch_related_objects(self) -> None:
        prefetch_related_objects(self._result_cache, *self._prefetch_related_lookups)
        self._prefetch_done = True

    def _clone(self) -> RawQuerySet:
        """Same as QuerySet._clone()"""
        c = self.__class__(
            self.raw_query,
            model=self.model,
            query=self.sql_query,
            params=self.params,
            translations=self.translations,
        )
        c._prefetch_related_lookups = self._prefetch_related_lookups[:]
        return c

    def _fetch_all(self) -> None:
        if self._result_cache is None:
            self._result_cache = list(self.iterator())
        if self._prefetch_related_lookups and not self._prefetch_done:
            self._prefetch_related_objects()

    def __len__(self) -> int:
        self._fetch_all()
        return len(self._result_cache)  # type: ignore[arg-type]

    def __bool__(self) -> bool:
        self._fetch_all()
        return bool(self._result_cache)

    def __iter__(self) -> Iterator[Model]:
        self._fetch_all()
        return iter(self._result_cache)  # type: ignore[arg-type]

    def iterator(self) -> Iterator[Model]:
        yield from RawModelIterable(self)

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__}: {self.sql_query}>"

    def __getitem__(self, k: int | slice) -> Model | list[Model]:
        return list(self)[k]

    @cached_property
    def columns(self) -> list[str]:
        """
        A list of model field names in the order they'll appear in the
        query results.
        """
        columns = self.sql_query.get_columns()
        # Adjust any column names which don't match field names
        for query_name, model_name in self.translations.items():
            # Ignore translations for nonexistent column names
            try:
                index = columns.index(query_name)
            except ValueError:
                pass
            else:
                columns[index] = model_name
        return columns

    @cached_property
    def model_fields(self) -> dict[str, Field]:
        """A dict mapping column names to model field names."""
        converter = db_connection.introspection.identifier_converter
        model_fields = {}
        for field in self.model._model_meta.fields:
            name, column = field.get_attname_column()
            model_fields[converter(column)] = field
        return model_fields


class Prefetch:
    def __init__(
        self,
        lookup: str,
        queryset: QuerySet[Any] | None = None,
        to_attr: str | None = None,
    ):
        # `prefetch_through` is the path we traverse to perform the prefetch.
        self.prefetch_through = lookup
        # `prefetch_to` is the path to the attribute that stores the result.
        self.prefetch_to = lookup
        if queryset is not None and (
            isinstance(queryset, RawQuerySet)
            or (
                hasattr(queryset, "_iterable_class")
                and not issubclass(queryset._iterable_class, ModelIterable)
            )
        ):
            raise ValueError(
                "Prefetch querysets cannot use raw(), values(), and values_list()."
            )
        if to_attr:
            self.prefetch_to = LOOKUP_SEP.join(
                lookup.split(LOOKUP_SEP)[:-1] + [to_attr]
            )

        self.queryset = queryset
        self.to_attr = to_attr

    def __getstate__(self) -> dict[str, Any]:
        obj_dict = self.__dict__.copy()
        if self.queryset is not None:
            queryset = self.queryset._chain()
            # Prevent the QuerySet from being evaluated
            queryset._result_cache = []
            queryset._prefetch_done = True
            obj_dict["queryset"] = queryset
        return obj_dict

    def add_prefix(self, prefix: str) -> None:
        self.prefetch_through = prefix + LOOKUP_SEP + self.prefetch_through
        self.prefetch_to = prefix + LOOKUP_SEP + self.prefetch_to

    def get_current_prefetch_to(self, level: int) -> str:
        return LOOKUP_SEP.join(self.prefetch_to.split(LOOKUP_SEP)[: level + 1])

    def get_current_to_attr(self, level: int) -> tuple[str, bool]:
        parts = self.prefetch_to.split(LOOKUP_SEP)
        to_attr = parts[level]
        as_attr = self.to_attr and level == len(parts) - 1
        return to_attr, as_attr

    def get_current_queryset(self, level: int) -> QuerySet[Any] | None:
        if self.get_current_prefetch_to(level) == self.prefetch_to:
            return self.queryset
        return None

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Prefetch):
            return NotImplemented
        return self.prefetch_to == other.prefetch_to

    def __hash__(self) -> int:
        return hash((self.__class__, self.prefetch_to))


def normalize_prefetch_lookups(
    lookups: tuple[str | Prefetch, ...] | list[str | Prefetch],
    prefix: str | None = None,
) -> list[Prefetch]:
    """Normalize lookups into Prefetch objects."""
    ret = []
    for lookup in lookups:
        if not isinstance(lookup, Prefetch):
            lookup = Prefetch(lookup)
        if prefix:
            lookup.add_prefix(prefix)
        ret.append(lookup)
    return ret


def prefetch_related_objects(
    model_instances: list[Model], *related_lookups: str | Prefetch
) -> None:
    """
    Populate prefetched object caches for a list of model instances based on
    the lookups/Prefetch instances given.
    """
    if not model_instances:
        return  # nothing to do

    # We need to be able to dynamically add to the list of prefetch_related
    # lookups that we look up (see below).  So we need some book keeping to
    # ensure we don't do duplicate work.
    done_queries = {}  # dictionary of things like 'foo__bar': [results]

    auto_lookups = set()  # we add to this as we go through.
    followed_descriptors = set()  # recursion protection

    all_lookups = normalize_prefetch_lookups(reversed(related_lookups))  # type: ignore[arg-type]
    while all_lookups:
        lookup = all_lookups.pop()
        if lookup.prefetch_to in done_queries:
            if lookup.queryset is not None:
                raise ValueError(
                    f"'{lookup.prefetch_to}' lookup was already seen with a different queryset. "
                    "You may need to adjust the ordering of your lookups."
                )

            continue

        # Top level, the list of objects to decorate is the result cache
        # from the primary QuerySet. It won't be for deeper levels.
        obj_list = model_instances

        through_attrs = lookup.prefetch_through.split(LOOKUP_SEP)
        for level, through_attr in enumerate(through_attrs):
            # Prepare main instances
            if not obj_list:
                break

            prefetch_to = lookup.get_current_prefetch_to(level)
            if prefetch_to in done_queries:
                # Skip any prefetching, and any object preparation
                obj_list = done_queries[prefetch_to]
                continue

            # Prepare objects:
            good_objects = True
            for obj in obj_list:
                # Since prefetching can re-use instances, it is possible to have
                # the same instance multiple times in obj_list, so obj might
                # already be prepared.
                if not hasattr(obj, "_prefetched_objects_cache"):
                    try:
                        obj._prefetched_objects_cache = {}
                    except (AttributeError, TypeError):
                        # Must be an immutable object from
                        # values_list(flat=True), for example (TypeError) or
                        # a QuerySet subclass that isn't returning Model
                        # instances (AttributeError), either in Plain or a 3rd
                        # party. prefetch_related() doesn't make sense, so quit.
                        good_objects = False
                        break
            if not good_objects:
                break

            # Descend down tree

            # We assume that objects retrieved are homogeneous (which is the premise
            # of prefetch_related), so what applies to first object applies to all.
            first_obj = obj_list[0]
            to_attr = lookup.get_current_to_attr(level)[0]
            prefetcher, descriptor, attr_found, is_fetched = get_prefetcher(
                first_obj, through_attr, to_attr
            )

            if not attr_found:
                raise AttributeError(
                    f"Cannot find '{through_attr}' on {first_obj.__class__.__name__} object, '{lookup.prefetch_through}' is an invalid "
                    "parameter to prefetch_related()"
                )

            if level == len(through_attrs) - 1 and prefetcher is None:
                # Last one, this *must* resolve to something that supports
                # prefetching, otherwise there is no point adding it and the
                # developer asking for it has made a mistake.
                raise ValueError(
                    f"'{lookup.prefetch_through}' does not resolve to an item that supports "
                    "prefetching - this is an invalid parameter to "
                    "prefetch_related()."
                )

            obj_to_fetch = None
            if prefetcher is not None:
                obj_to_fetch = [obj for obj in obj_list if not is_fetched(obj)]

            if obj_to_fetch:
                obj_list, additional_lookups = prefetch_one_level(
                    obj_to_fetch,
                    prefetcher,
                    lookup,
                    level,
                )
                # We need to ensure we don't keep adding lookups from the
                # same relationships to stop infinite recursion. So, if we
                # are already on an automatically added lookup, don't add
                # the new lookups from relationships we've seen already.
                if not (
                    prefetch_to in done_queries
                    and lookup in auto_lookups
                    and descriptor in followed_descriptors
                ):
                    done_queries[prefetch_to] = obj_list
                    new_lookups = normalize_prefetch_lookups(
                        reversed(additional_lookups),  # type: ignore[arg-type]
                        prefetch_to,
                    )
                    auto_lookups.update(new_lookups)
                    all_lookups.extend(new_lookups)
                followed_descriptors.add(descriptor)
            else:
                # Either a singly related object that has already been fetched
                # (e.g. via select_related), or hopefully some other property
                # that doesn't support prefetching but needs to be traversed.

                # We replace the current list of parent objects with the list
                # of related objects, filtering out empty or missing values so
                # that we can continue with nullable or reverse relations.
                new_obj_list = []
                for obj in obj_list:
                    if through_attr in getattr(obj, "_prefetched_objects_cache", ()):
                        # If related objects have been prefetched, use the
                        # cache rather than the object's through_attr.
                        new_obj = list(obj._prefetched_objects_cache.get(through_attr))  # type: ignore[arg-type]
                    else:
                        try:
                            new_obj = getattr(obj, through_attr)
                        except ObjectDoesNotExist:
                            continue
                    if new_obj is None:
                        continue
                    # We special-case `list` rather than something more generic
                    # like `Iterable` because we don't want to accidentally match
                    # user models that define __iter__.
                    if isinstance(new_obj, list):
                        new_obj_list.extend(new_obj)
                    else:
                        new_obj_list.append(new_obj)
                obj_list = new_obj_list


def get_prefetcher(
    instance: Model, through_attr: str, to_attr: str
) -> tuple[Any, Any, bool, Callable[[Model], bool]]:
    """
    For the attribute 'through_attr' on the given instance, find
    an object that has a get_prefetch_queryset().
    Return a 4 tuple containing:
    (the object with get_prefetch_queryset (or None),
     the descriptor object representing this relationship (or None),
     a boolean that is False if the attribute was not found at all,
     a function that takes an instance and returns a boolean that is True if
     the attribute has already been fetched for that instance)
    """

    def has_to_attr_attribute(instance: Model) -> bool:
        return hasattr(instance, to_attr)

    prefetcher = None
    is_fetched: Callable[[Model], bool] = has_to_attr_attribute

    # For singly related objects, we have to avoid getting the attribute
    # from the object, as this will trigger the query. So we first try
    # on the class, in order to get the descriptor object.
    rel_obj_descriptor = getattr(instance.__class__, through_attr, None)
    if rel_obj_descriptor is None:
        attr_found = hasattr(instance, through_attr)
    else:
        attr_found = True
        if rel_obj_descriptor:
            # singly related object, descriptor object has the
            # get_prefetch_queryset() method.
            if hasattr(rel_obj_descriptor, "get_prefetch_queryset"):
                prefetcher = rel_obj_descriptor
                is_fetched = rel_obj_descriptor.is_cached
            else:
                # descriptor doesn't support prefetching, so we go ahead and get
                # the attribute on the instance rather than the class to
                # support many related managers
                rel_obj = getattr(instance, through_attr)
                if hasattr(rel_obj, "get_prefetch_queryset"):
                    prefetcher = rel_obj
                if through_attr != to_attr:
                    # Special case cached_property instances because hasattr
                    # triggers attribute computation and assignment.
                    if isinstance(
                        getattr(instance.__class__, to_attr, None), cached_property
                    ):

                        def has_cached_property(instance: Model) -> bool:
                            return to_attr in instance.__dict__

                        is_fetched = has_cached_property
                else:

                    def in_prefetched_cache(instance: Model) -> bool:
                        return through_attr in instance._prefetched_objects_cache  # type: ignore[attr-defined]

                    is_fetched = in_prefetched_cache
    return prefetcher, rel_obj_descriptor, attr_found, is_fetched


def prefetch_one_level(
    instances: list[Model], prefetcher: Any, lookup: Prefetch, level: int
) -> tuple[list[Model], list[Prefetch]]:
    """
    Helper function for prefetch_related_objects().

    Run prefetches on all instances using the prefetcher object,
    assigning results to relevant caches in instance.

    Return the prefetched objects along with any additional prefetches that
    must be done due to prefetch_related lookups found from default managers.
    """
    # prefetcher must have a method get_prefetch_queryset() which takes a list
    # of instances, and returns a tuple:

    # (queryset of instances of self.model that are related to passed in instances,
    #  callable that gets value to be matched for returned instances,
    #  callable that gets value to be matched for passed in instances,
    #  boolean that is True for singly related objects,
    #  cache or field name to assign to,
    #  boolean that is True when the previous argument is a cache name vs a field name).

    # The 'values to be matched' must be hashable as they will be used
    # in a dictionary.

    (
        rel_qs,
        rel_obj_attr,
        instance_attr,
        single,
        cache_name,
        is_descriptor,
    ) = prefetcher.get_prefetch_queryset(instances, lookup.get_current_queryset(level))
    # We have to handle the possibility that the QuerySet we just got back
    # contains some prefetch_related lookups. We don't want to trigger the
    # prefetch_related functionality by evaluating the query. Rather, we need
    # to merge in the prefetch_related lookups.
    # Copy the lookups in case it is a Prefetch object which could be reused
    # later (happens in nested prefetch_related).
    additional_lookups = [
        copy.copy(additional_lookup)
        for additional_lookup in getattr(rel_qs, "_prefetch_related_lookups", ())
    ]
    if additional_lookups:
        # Don't need to clone because the queryset should have given us a fresh
        # instance, so we access an internal instead of using public interface
        # for performance reasons.
        rel_qs._prefetch_related_lookups = ()

    all_related_objects = list(rel_qs)

    rel_obj_cache = {}
    for rel_obj in all_related_objects:
        rel_attr_val = rel_obj_attr(rel_obj)
        rel_obj_cache.setdefault(rel_attr_val, []).append(rel_obj)

    to_attr, as_attr = lookup.get_current_to_attr(level)
    # Make sure `to_attr` does not conflict with a field.
    if as_attr and instances:
        # We assume that objects retrieved are homogeneous (which is the premise
        # of prefetch_related), so what applies to first object applies to all.
        model = instances[0].__class__
        try:
            model._model_meta.get_field(to_attr)
        except FieldDoesNotExist:
            pass
        else:
            msg = "to_attr={} conflicts with a field on the {} model."
            raise ValueError(msg.format(to_attr, model.__name__))

    # Whether or not we're prefetching the last part of the lookup.
    leaf = len(lookup.prefetch_through.split(LOOKUP_SEP)) - 1 == level

    for obj in instances:
        instance_attr_val = instance_attr(obj)
        vals = rel_obj_cache.get(instance_attr_val, [])

        if single:
            val = vals[0] if vals else None
            if as_attr:
                # A to_attr has been given for the prefetch.
                setattr(obj, to_attr, val)
            elif is_descriptor:
                # cache_name points to a field name in obj.
                # This field is a descriptor for a related object.
                setattr(obj, cache_name, val)
            else:
                # No to_attr has been given for this prefetch operation and the
                # cache_name does not point to a descriptor. Store the value of
                # the field in the object's field cache.
                obj._state.fields_cache[cache_name] = val  # type: ignore[index]
        else:
            if as_attr:
                setattr(obj, to_attr, vals)
            else:
                queryset = getattr(obj, to_attr)
                if leaf and lookup.queryset is not None:
                    qs = queryset._apply_rel_filters(lookup.queryset)
                else:
                    # Check if queryset is a QuerySet or a related manager
                    # We need a QuerySet instance to cache the prefetched values
                    if isinstance(queryset, QuerySet):
                        # It's already a QuerySet, create a new instance
                        qs = queryset.__class__.from_model(queryset.model)
                    else:
                        # It's a related manager, get its QuerySet
                        # The manager's query property returns a properly filtered QuerySet
                        qs = queryset.query
                qs._result_cache = vals
                # We don't want the individual qs doing prefetch_related now,
                # since we have merged this into the current work.
                qs._prefetch_done = True
                obj._prefetched_objects_cache[cache_name] = qs
    return all_related_objects, additional_lookups


class RelatedPopulator:
    """
    RelatedPopulator is used for select_related() object instantiation.

    The idea is that each select_related() model will be populated by a
    different RelatedPopulator instance. The RelatedPopulator instances get
    klass_info and select (computed in SQLCompiler) plus the used db as
    input for initialization. That data is used to compute which columns
    to use, how to instantiate the model, and how to populate the links
    between the objects.

    The actual creation of the objects is done in populate() method. This
    method gets row and from_obj as input and populates the select_related()
    model instance.
    """

    def __init__(self, klass_info: dict[str, Any], select: list[Any]):
        # Pre-compute needed attributes. The attributes are:
        #  - model_cls: the possibly deferred model class to instantiate
        #  - either:
        #    - cols_start, cols_end: usually the columns in the row are
        #      in the same order model_cls.__init__ expects them, so we
        #      can instantiate by model_cls(*row[cols_start:cols_end])
        #    - reorder_for_init: When select_related descends to a child
        #      class, then we want to reuse the already selected parent
        #      data. However, in this case the parent data isn't necessarily
        #      in the same order that Model.__init__ expects it to be, so
        #      we have to reorder the parent data. The reorder_for_init
        #      attribute contains a function used to reorder the field data
        #      in the order __init__ expects it.
        #  - id_idx: the index of the primary key field in the reordered
        #    model data. Used to check if a related object exists at all.
        #  - init_list: the field attnames fetched from the database. For
        #    deferred models this isn't the same as all attnames of the
        #    model's fields.
        #  - related_populators: a list of RelatedPopulator instances if
        #    select_related() descends to related models from this model.
        #  - local_setter, remote_setter: Methods to set cached values on
        #    the object being populated and on the remote object. Usually
        #    these are Field.set_cached_value() methods.
        select_fields = klass_info["select_fields"]

        self.cols_start = select_fields[0]
        self.cols_end = select_fields[-1] + 1
        self.init_list = [
            f[0].target.attname for f in select[self.cols_start : self.cols_end]
        ]
        self.reorder_for_init = None

        self.model_cls = klass_info["model"]
        self.id_idx = self.init_list.index("id")
        self.related_populators = get_related_populators(klass_info, select)
        self.local_setter = klass_info["local_setter"]
        self.remote_setter = klass_info["remote_setter"]

    def populate(self, row: tuple[Any, ...], from_obj: Model) -> None:
        if self.reorder_for_init:
            obj_data = self.reorder_for_init(row)
        else:
            obj_data = row[self.cols_start : self.cols_end]
        if obj_data[self.id_idx] is None:
            obj = None
        else:
            obj = self.model_cls.from_db(self.init_list, obj_data)
            for rel_iter in self.related_populators:
                rel_iter.populate(row, obj)
        self.local_setter(from_obj, obj)
        if obj is not None:
            self.remote_setter(obj, from_obj)


def get_related_populators(
    klass_info: dict[str, Any], select: list[Any]
) -> list[RelatedPopulator]:
    iterators = []
    related_klass_infos = klass_info.get("related_klass_infos", [])
    for rel_klass_info in related_klass_infos:
        rel_cls = RelatedPopulator(rel_klass_info, select)
        iterators.append(rel_cls)
    return iterators
