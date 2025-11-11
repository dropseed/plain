"""
Various data structures used in query construction.

Factored out from plain.models.query to avoid making the main module very
large and/or so that they can be used by other modules without getting into
circular import difficulties.
"""

from __future__ import annotations

import functools
import inspect
import logging
from collections import namedtuple
from collections.abc import Generator
from typing import TYPE_CHECKING, Any

from plain.models.constants import LOOKUP_SEP
from plain.models.db import DatabaseError, db_connection
from plain.models.exceptions import FieldError
from plain.utils import tree

if TYPE_CHECKING:
    from plain.models.backends.base.base import BaseDatabaseWrapper
    from plain.models.base import Model
    from plain.models.fields import Field
    from plain.models.meta import Meta
    from plain.models.sql.compiler import SQLCompiler

logger = logging.getLogger("plain.models")

# PathInfo is used when converting lookups (fk__somecol). The contents
# describe the relation in Model terms (Meta and Fields for both
# sides of the relation). The join_field is the field backing the relation.
PathInfo = namedtuple(
    "PathInfo",
    "from_meta to_meta target_fields join_field m2m direct filtered_relation",
)


def subclasses(cls: type) -> Generator[type, None, None]:
    yield cls
    for subclass in cls.__subclasses__():
        yield from subclasses(subclass)


class Q(tree.Node):
    """
    Encapsulate filters as objects that can then be combined logically (using
    `&` and `|`).
    """

    # Connection types
    AND = "AND"
    OR = "OR"
    XOR = "XOR"
    default = AND
    conditional = True

    def __init__(
        self,
        *args: Any,
        _connector: str | None = None,
        _negated: bool = False,
        **kwargs: Any,
    ) -> None:
        super().__init__(
            children=[*args, *sorted(kwargs.items())],
            connector=_connector,
            negated=_negated,
        )

    def _combine(self, other: Any, conn: str) -> Q:
        if getattr(other, "conditional", False) is False:
            raise TypeError(other)
        if not self:
            return other.copy()
        if not other and isinstance(other, Q):
            return self.copy()

        obj = self.create(connector=conn)
        obj.add(self, conn)
        obj.add(other, conn)
        return obj

    def __or__(self, other: Any) -> Q:
        return self._combine(other, self.OR)

    def __and__(self, other: Any) -> Q:
        return self._combine(other, self.AND)

    def __xor__(self, other: Any) -> Q:
        return self._combine(other, self.XOR)

    def __invert__(self) -> Q:
        obj = self.copy()
        obj.negate()
        return obj

    def resolve_expression(
        self,
        query: Any = None,
        allow_joins: bool = True,
        reuse: Any = None,
        summarize: bool = False,
        for_save: bool = False,
    ) -> Any:
        # We must promote any new joins to left outer joins so that when Q is
        # used as an expression, rows aren't filtered due to joins.
        clause, joins = query._add_q(  # type: ignore[union-attr]
            self,
            reuse,
            allow_joins=allow_joins,
            split_subq=False,
            check_filterable=False,
            summarize=summarize,
        )
        query.promote_joins(joins)  # type: ignore[union-attr]
        return clause

    def flatten(self) -> Generator[Any, None, None]:
        """
        Recursively yield this Q object and all subexpressions, in depth-first
        order.
        """
        yield self
        for child in self.children:
            if isinstance(child, tuple):
                # Use the lookup.
                child = child[1]
            if hasattr(child, "flatten"):
                yield from child.flatten()
            else:
                yield child

    def check(self, against: dict[str, Any]) -> bool:
        """
        Do a database query to check if the expressions of the Q instance
        matches against the expressions.
        """
        # Avoid circular imports.
        from plain.models.expressions import Value
        from plain.models.fields import BooleanField
        from plain.models.functions import Coalesce
        from plain.models.sql import Query
        from plain.models.sql.constants import SINGLE

        query = Query(None)  # type: ignore[arg-type]
        for name, value in against.items():
            if not hasattr(value, "resolve_expression"):
                value = Value(value)
            query.add_annotation(value, name, select=False)
        query.add_annotation(Value(1), "_check")
        # This will raise a FieldError if a field is missing in "against".
        if db_connection.features.supports_comparing_boolean_expr:
            query.add_q(Q(Coalesce(self, True, output_field=BooleanField())))
        else:
            query.add_q(self)
        compiler = query.get_compiler()
        try:
            return compiler.execute_sql(SINGLE) is not None
        except DatabaseError as e:
            logger.warning("Got a database error calling check() on %r: %s", self, e)
            return True

    def deconstruct(self) -> tuple[str, tuple[Any, ...], dict[str, Any]]:
        path = f"{self.__class__.__module__}.{self.__class__.__name__}"
        if path.startswith("plain.models.query_utils"):
            path = path.replace("plain.models.query_utils", "plain.models")
        args = tuple(self.children)
        kwargs: dict[str, Any] = {}
        if self.connector != self.default:
            kwargs["_connector"] = self.connector
        if self.negated:
            kwargs["_negated"] = True
        return path, args, kwargs


class class_or_instance_method:
    """
    Hook used in RegisterLookupMixin to return partial functions depending on
    the caller type (instance or class of models.Field).
    """

    def __init__(self, class_method: Any, instance_method: Any) -> None:
        self.class_method = class_method
        self.instance_method = instance_method

    def __get__(self, instance: Any, owner: type) -> Any:
        if instance is None:
            return functools.partial(self.class_method, owner)
        return functools.partial(self.instance_method, instance)


class RegisterLookupMixin:
    def _get_lookup(self, lookup_name: str) -> type | None:
        return self.get_lookups().get(lookup_name, None)

    @functools.cache
    def get_class_lookups(cls: type) -> dict[str, type]:
        class_lookups = [
            parent.__dict__.get("class_lookups", {}) for parent in inspect.getmro(cls)
        ]
        return cls.merge_dicts(class_lookups)  # type: ignore[attr-defined]

    def get_instance_lookups(self) -> dict[str, type]:
        class_lookups = self.get_class_lookups()
        if instance_lookups := getattr(self, "instance_lookups", None):
            return {**class_lookups, **instance_lookups}
        return class_lookups

    get_lookups = class_or_instance_method(get_class_lookups, get_instance_lookups)
    get_class_lookups = classmethod(get_class_lookups)  # type: ignore[assignment]

    def get_lookup(self, lookup_name: str) -> type | None:
        from plain.models.lookups import Lookup

        found = self._get_lookup(lookup_name)
        if found is None and hasattr(self, "output_field"):
            return self.output_field.get_lookup(lookup_name)
        if found is not None and not issubclass(found, Lookup):
            return None
        return found

    def get_transform(self, lookup_name: str) -> type | None:
        from plain.models.lookups import Transform

        found = self._get_lookup(lookup_name)
        if found is None and hasattr(self, "output_field"):
            return self.output_field.get_transform(lookup_name)
        if found is not None and not issubclass(found, Transform):
            return None
        return found

    @staticmethod
    def merge_dicts(dicts: list[dict[str, type]]) -> dict[str, type]:
        """
        Merge dicts in reverse to preference the order of the original list. e.g.,
        merge_dicts([a, b]) will preference the keys in 'a' over those in 'b'.
        """
        merged: dict[str, type] = {}
        for d in reversed(dicts):
            merged.update(d)
        return merged

    @classmethod
    def _clear_cached_class_lookups(cls) -> None:
        for subclass in subclasses(cls):
            subclass.get_class_lookups.cache_clear()  # type: ignore[attr-defined]

    def register_class_lookup(
        cls: type, lookup: type, lookup_name: str | None = None
    ) -> type:
        if lookup_name is None:
            lookup_name = lookup.lookup_name  # type: ignore[attr-defined]
        if "class_lookups" not in cls.__dict__:
            cls.class_lookups = {}  # type: ignore[attr-defined]
        cls.class_lookups[lookup_name] = lookup  # type: ignore[attr-defined]
        cls._clear_cached_class_lookups()  # type: ignore[attr-defined]
        return lookup

    def register_instance_lookup(
        self, lookup: type, lookup_name: str | None = None
    ) -> type:
        if lookup_name is None:
            lookup_name = lookup.lookup_name  # type: ignore[attr-defined]
        if "instance_lookups" not in self.__dict__:
            self.instance_lookups = {}
        self.instance_lookups[lookup_name] = lookup
        return lookup

    register_lookup = class_or_instance_method(
        register_class_lookup, register_instance_lookup
    )
    register_class_lookup = classmethod(register_class_lookup)  # type: ignore[assignment]

    def _unregister_class_lookup(
        cls: type, lookup: type, lookup_name: str | None = None
    ) -> None:
        """
        Remove given lookup from cls lookups. For use in tests only as it's
        not thread-safe.
        """
        if lookup_name is None:
            lookup_name = lookup.lookup_name  # type: ignore[attr-defined]
        del cls.class_lookups[lookup_name]  # type: ignore[attr-defined]
        cls._clear_cached_class_lookups()  # type: ignore[attr-defined]

    def _unregister_instance_lookup(
        self, lookup: type, lookup_name: str | None = None
    ) -> None:
        """
        Remove given lookup from instance lookups. For use in tests only as
        it's not thread-safe.
        """
        if lookup_name is None:
            lookup_name = lookup.lookup_name  # type: ignore[attr-defined]
        del self.instance_lookups[lookup_name]

    _unregister_lookup = class_or_instance_method(
        _unregister_class_lookup, _unregister_instance_lookup
    )
    _unregister_class_lookup = classmethod(_unregister_class_lookup)  # type: ignore[assignment]


def select_related_descend(
    field: Any,
    restricted: bool,
    requested: dict[str, Any],
    select_mask: Any,
    reverse: bool = False,
) -> bool:
    """
    Return True if this field should be used to descend deeper for
    select_related() purposes. Used by both the query construction code
    (compiler.get_related_selections()) and the model instance creation code
    (compiler.klass_info).

    Arguments:
     * field - the field to be checked
     * restricted - a boolean field, indicating if the field list has been
       manually restricted using a requested clause)
     * requested - The select_related() dictionary.
     * select_mask - the dictionary of selected fields.
     * reverse - boolean, True if we are checking a reverse select related
    """
    if not field.remote_field:
        return False
    if restricted:
        if reverse and field.related_query_name() not in requested:
            return False
        if not reverse and field.name not in requested:
            return False
    if not restricted and field.allow_null:
        return False
    if (
        restricted
        and select_mask
        and field.name in requested
        and field not in select_mask
    ):
        raise FieldError(
            f"Field {field.model.model_options.object_name}.{field.name} cannot be both "
            "deferred and traversed using select_related at the same time."
        )
    return True


def refs_expression(
    lookup_parts: list[str], annotations: dict[str, Any]
) -> tuple[str | None, tuple[str, ...]]:
    """
    Check if the lookup_parts contains references to the given annotations set.
    Because the LOOKUP_SEP is contained in the default annotation names, check
    each prefix of the lookup_parts for a match.
    """
    for n in range(1, len(lookup_parts) + 1):
        level_n_lookup = LOOKUP_SEP.join(lookup_parts[0:n])
        if annotations.get(level_n_lookup):
            return level_n_lookup, tuple(lookup_parts[n:])
    return None, ()


def check_rel_lookup_compatibility(
    model: type[Model], target_meta: Meta, field: Field
) -> bool:
    """
    Check that model is compatible with target_meta. Compatibility
    is OK if:
      1) model and meta.model match (where proxy inheritance is removed)
      2) model is parent of meta's model or the other way around
    """

    def check(meta: Meta) -> bool:
        return model == meta.model

    # If the field is a primary key, then doing a query against the field's
    # model is ok, too. Consider the case:
    # class Restaurant(models.Model):
    #     place = OneToOneField(Place, primary_key=True):
    # Restaurant.query.filter(id__in=Restaurant.query.all()).
    # If we didn't have the primary key check, then id__in (== place__in) would
    # give Place's meta as the target meta, but Restaurant isn't compatible
    # with that. This logic applies only to primary keys, as when doing __in=qs,
    # we are going to turn this into __in=qs.values('id') later on.
    return check(target_meta) or (
        getattr(field, "primary_key", False) and check(field.model._model_meta)
    )


class FilteredRelation:
    """Specify custom filtering in the ON clause of SQL joins."""

    def __init__(self, relation_name: str, *, condition: Q = Q()) -> None:
        if not relation_name:
            raise ValueError("relation_name cannot be empty.")
        self.relation_name = relation_name
        self.alias: str | None = None
        if not isinstance(condition, Q):
            raise ValueError("condition argument must be a Q() instance.")
        self.condition = condition
        self.path: list[str] = []

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, self.__class__):
            return NotImplemented
        return (
            self.relation_name == other.relation_name
            and self.alias == other.alias
            and self.condition == other.condition
        )

    def clone(self) -> FilteredRelation:
        clone = FilteredRelation(self.relation_name, condition=self.condition)
        clone.alias = self.alias
        clone.path = self.path[:]
        return clone

    def resolve_expression(self, *args: Any, **kwargs: Any) -> Any:
        """
        QuerySet.annotate() only accepts expression-like arguments
        (with a resolve_expression() method).
        """
        raise NotImplementedError("FilteredRelation.resolve_expression() is unused.")

    def as_sql(self, compiler: SQLCompiler, connection: BaseDatabaseWrapper) -> Any:
        # Resolve the condition in Join.filtered_relation.
        query = compiler.query
        where = query.build_filtered_relation_q(self.condition, reuse=set(self.path))
        return compiler.compile(where)
