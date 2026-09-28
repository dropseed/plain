"""
Various data structures used in query construction.

Factored out from plain.postgres.query to avoid making the main module very
large and/or so that they can be used by other modules without getting into
circular import difficulties.
"""

import functools
import inspect
from collections.abc import Callable, Generator, Iterable
from typing import TYPE_CHECKING, Any, ClassVar, NamedTuple, Self, TypeGuard

import psycopg
from plain.logs import get_framework_logger
from plain.postgres.constants import LOOKUP_SEP
from plain.postgres.exceptions import FieldError
from plain.utils import tree

if TYPE_CHECKING:
    from plain.postgres.base import Model
    from plain.postgres.fields import Field
    from plain.postgres.fields.related import ForeignKeyField, RelatedField
    from plain.postgres.fields.reverse_related import ForeignKeyRel, ForeignObjectRel
    from plain.postgres.lookups import Lookup, Transform
    from plain.postgres.meta import Meta
    from plain.postgres.sql.where import WhereNode

logger = get_framework_logger()


class PathInfo(NamedTuple):
    """Information about a relation path when converting lookups (fk__somecol).

    Describes the relation in Model terms (Meta and Fields for both
    sides of the relation). The join_field is the field backing the relation.
    """

    from_meta: Meta
    to_meta: Meta
    target_field: Field
    join_field: ForeignKeyField | ForeignKeyRel
    m2m: bool
    direct: bool


def subclasses(cls: type) -> Generator[type]:
    yield cls
    for subclass in cls.__subclasses__():
        yield from subclasses(subclass)


def condition_origins_of(condition: Any) -> frozenset[tuple[type[Model], str]]:
    """The (model, field name) pairs that built `condition`, or nothing.

    `Q` combines with any object that sets `conditional = True` -- an
    expression, for instance -- so this can't assume a `Q`. It can't assume
    the attribute means what we mean either: a conditional object with a
    catch-all `__getattr__` would hand back something arbitrary and break
    every Q construction path with an opaque error from `|=`. Anything that
    isn't the frozenset we put there is treated as no origins at all.
    """
    origins = getattr(condition, "_condition_origins", None)
    return origins if isinstance(origins, frozenset) else frozenset()


def _collect_condition_origins(
    children: Iterable[Any],
) -> frozenset[tuple[type[Model], str]]:
    """Union the sources of `children`, which are a node's immediate children.

    Only one level deep: each child already carries its own subtree's sources,
    so this never walks the tree.
    """
    sources: frozenset[tuple[type[Model], str]] = frozenset()
    for child in children:
        sources |= condition_origins_of(child)
    return sources


class Q(tree.Node):
    """
    Encapsulate filters as objects that can then be combined logically (using
    `&` and `|`).
    """

    # Connection types
    AND = "AND"
    OR = "OR"
    default = AND
    conditional = True

    # The (model, field name) pairs that built this Q, stamped by
    # `Field._build_q` and carried through wrapping, copying and combining
    # below. `where()` reads it to reject a condition built from another
    # model's field; a Q written by hand (`Q(name="x")`) names no source and is
    # never checked.
    #
    # It lives on the node rather than on the leaves, so every method that
    # builds or extends a Q has to carry it forward -- a guard with a way
    # around it is not a guard. The complete set, all overridden below:
    #
    #   __init__     Q(cond), and the wrappers BaseExpression.__and__ builds
    #   create()     the classmethod Node uses to rebuild a Q; it constructs a
    #                plain Node and reassigns __class__, so __init__ never runs
    #   add()        mutates children in place: q = Q(); q.add(cond, Q.AND)
    #   __copy__     which ~q and Node.copy() both go through
    #   __deepcopy__
    #
    # `_combine` (&, |) is built from `create` + `add` and so needs nothing of
    # its own. Pickling preserves the instance attribute as-is. Each of these
    # reads only its immediate children, which already carry their own
    # subtree's sources, so nothing walks the tree. The one way left to put a
    # condition into a Q without recording it is appending to `q.children`
    # directly, which is reaching past the API into Node's internals.
    _condition_origins: frozenset[tuple[type[Model], str]] = frozenset()

    @classmethod
    def create(
        cls,
        children: list[Any] | None = None,
        connector: str | None = None,
        negated: bool = False,
    ) -> Self:
        # `Node.create` builds a plain Node and reassigns __class__, so
        # `Q.__init__` never runs and the children's sources would be dropped.
        obj = super().create(children, connector, negated)
        obj._condition_origins = _collect_condition_origins(children or ())
        return obj

    def add(self, data: Any, conn_type: str) -> Any:
        # `Node.add` mutates `children` in place, so a Q built up by hand --
        # `q = Q(); q.add(cond, Q.AND)` -- would otherwise never record what
        # went into it.
        added = super().add(data, conn_type)
        self._condition_origins |= condition_origins_of(data)
        return added

    def __copy__(self) -> Q:
        obj = super().__copy__()
        # `Node.__copy__` hands the *same* children list to the copy, so
        # `alias = base.copy(); alias.add(cond, Q.AND)` appends into `base`
        # while only `alias` records the origin -- base would then carry a
        # condition it doesn't know about. Give the copy its own list; the
        # children themselves are still shared, which is what makes a copy
        # cheap. (`__deepcopy__` already rebuilds the list.)
        obj.children = self.children[:]
        obj._condition_origins = self._condition_origins
        return obj

    copy = __copy__

    def __deepcopy__(self, memodict: dict[int, Any]) -> Q:
        obj = super().__deepcopy__(memodict)
        obj._condition_origins = self._condition_origins
        return obj

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
        # Wrapping a condition keeps its sources, the same way combining two
        # does. `Exists(sub) & Model.field.equals(x)` runs through
        # `BaseExpression.__and__`, which wraps both sides in `Q(...)` before
        # combining -- without this the wrapper would report no sources and the
        # condition's origin would be lost.
        if sources := _collect_condition_origins(args):
            self._condition_origins = sources

    def _combine(self, other: Any, conn: str) -> Q:
        if getattr(other, "conditional", False) is False:
            raise TypeError(other)
        if not self:
            return other.copy()
        if not other and isinstance(other, Q):
            return self.copy()

        obj = self.create(connector=conn)
        # `add` collects each side's sources as it goes.
        obj.add(self, conn)
        obj.add(other, conn)
        return obj

    def __or__(self, other: Any) -> Q:
        return self._combine(other, self.OR)

    def __and__(self, other: Any) -> Q:
        return self._combine(other, self.AND)

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
    ) -> WhereNode:
        # We must promote any new joins to left outer joins so that when Q is
        # used as an expression, rows aren't filtered due to joins.
        clause, joins = query._add_q(
            self,
            reuse,
            allow_joins=allow_joins,
            split_subq=False,
            check_filterable=False,
            summarize=summarize,
        )
        query.promote_joins(joins)
        return clause

    def flatten(self) -> Generator[Any]:
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
        from plain.postgres.expressions import ResolvableExpression, Value
        from plain.postgres.fields import BooleanField
        from plain.postgres.functions import Coalesce
        from plain.postgres.sql import SINGLE, Query

        query = Query(None)
        for name, value in against.items():
            if not isinstance(value, ResolvableExpression):
                value = Value(value)
            query.add_annotation(value, name, select=False)
        query.add_annotation(Value(1), "_check")
        # This will raise a FieldError if a field is missing in "against".
        query.add_q(Q(Coalesce(self, True, output_field=BooleanField())))
        compiler = query.get_compiler()
        try:
            return compiler.execute_sql(SINGLE) is not None
        except psycopg.DatabaseError as e:
            logger.warning(
                "Got a database error calling check()",
                extra={"expression": repr(self), "error": str(e)},
            )
            return True

    def deconstruct(self) -> tuple[str, tuple[Any, ...], dict[str, Any]]:
        path = f"{self.__class__.__module__}.{self.__class__.__name__}"
        if path.startswith("plain.postgres.query_utils"):
            path = path.replace("plain.postgres.query_utils", "plain.postgres")
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
    class_lookups: ClassVar[dict[str, type[Lookup | Transform]]]

    def _get_lookup(self, lookup_name: str) -> type[Lookup | Transform] | None:
        return self.get_lookups().get(lookup_name, None)

    @functools.cache  # noqa: B019 — keyed by class; classes live for the process
    def get_class_lookups(cls: type[Self]) -> dict[str, type[Lookup | Transform]]:
        class_lookups = [
            parent.__dict__.get("class_lookups", {}) for parent in inspect.getmro(cls)
        ]
        return cls.merge_dicts(class_lookups)

    def get_instance_lookups(self) -> dict[str, type[Lookup | Transform]]:
        class_lookups = self.get_class_lookups()
        if instance_lookups := getattr(self, "instance_lookups", None):
            return {**class_lookups, **instance_lookups}
        return class_lookups

    get_lookups = class_or_instance_method(get_class_lookups, get_instance_lookups)
    get_class_lookups: ClassVar[classmethod[Any, ..., Any]] = classmethod(
        get_class_lookups
    )

    def get_lookup(self, lookup: str) -> type[Lookup] | None:
        from plain.postgres.lookups import Lookup

        found = self._get_lookup(lookup)
        # output_field is a Field which inherits from RegisterLookupMixin
        if found is None and (output_field := getattr(self, "output_field", None)):
            return output_field.get_lookup(lookup)
        if found is not None and not issubclass(found, Lookup):
            return None
        return found

    def get_transform(self, name: str) -> Callable[..., Transform] | None:
        from plain.postgres.lookups import Transform

        found = self._get_lookup(name)
        # output_field is a Field which inherits from RegisterLookupMixin
        if found is None and (output_field := getattr(self, "output_field", None)):
            return output_field.get_transform(name)
        if found is not None and not issubclass(found, Transform):
            return None
        return found

    @staticmethod
    def merge_dicts(
        dicts: list[dict[str, type[Lookup | Transform]]],
    ) -> dict[str, type[Lookup | Transform]]:
        """
        Merge dicts in reverse to preference the order of the original list. e.g.,
        merge_dicts([a, b]) will preference the keys in 'a' over those in 'b'.
        """
        merged: dict[str, type[Lookup | Transform]] = {}
        for d in reversed(dicts):
            merged.update(d)
        return merged

    @classmethod
    def _clear_cached_class_lookups(cls: type[Self]) -> None:
        for subclass in subclasses(cls):
            if cached := getattr(subclass, "get_class_lookups", None):
                cached.cache_clear()

    def register_class_lookup(
        cls: type[Self],
        lookup: type[Lookup | Transform],
        lookup_name: str | None = None,
    ) -> type[Lookup | Transform]:
        if lookup_name is None:
            lookup_name = lookup.lookup_name
        assert lookup_name is not None, "lookup_name must be set on the lookup class"
        if "class_lookups" not in cls.__dict__:
            cls.class_lookups = {}
        cls.class_lookups[lookup_name] = lookup
        cls._clear_cached_class_lookups()
        return lookup

    def register_instance_lookup(
        self, lookup: type[Lookup | Transform], lookup_name: str | None = None
    ) -> type[Lookup | Transform]:
        if lookup_name is None:
            lookup_name = lookup.lookup_name
        if "instance_lookups" not in self.__dict__:
            self.instance_lookups = {}
        self.instance_lookups[lookup_name] = lookup
        return lookup

    register_lookup = class_or_instance_method(
        register_class_lookup, register_instance_lookup
    )
    register_class_lookup: ClassVar[classmethod[Any, ..., Any]] = classmethod(
        register_class_lookup
    )

    def _unregister_class_lookup(
        cls: type[Self],
        lookup: type[Lookup | Transform],
        lookup_name: str | None = None,
    ) -> None:
        """
        Remove given lookup from cls lookups. For use in tests only as it's
        not thread-safe.
        """
        if lookup_name is None:
            lookup_name = lookup.lookup_name
        assert lookup_name is not None, "lookup_name must be set on the lookup class"
        del cls.class_lookups[lookup_name]
        cls._clear_cached_class_lookups()

    def _unregister_instance_lookup(
        self, lookup: type[Lookup | Transform], lookup_name: str | None = None
    ) -> None:
        """
        Remove given lookup from instance lookups. For use in tests only as
        it's not thread-safe.
        """
        if lookup_name is None:
            lookup_name = lookup.lookup_name
        del self.instance_lookups[lookup_name]

    _unregister_lookup = class_or_instance_method(
        _unregister_class_lookup, _unregister_instance_lookup
    )
    _unregister_class_lookup: ClassVar[classmethod[Any, ..., Any]] = classmethod(
        _unregister_class_lookup
    )


def join_relation_descend(
    field: Any,
    restricted: bool | None,
    requested: dict[str, Any] | None,
    select_mask: Any,
    reverse: bool = False,
) -> TypeGuard[RelatedField]:
    """
    Return True if this field should be used to descend deeper for
    join() purposes. Used by both the query construction code
    (compiler.get_related_selections()) and the model instance creation code
    (compiler.klass_info).

    Arguments:
     * field - the field to be checked
     * restricted - a boolean field, indicating if the field list has been
       manually restricted using a requested clause)
     * requested - The join() dictionary.
     * select_mask - the dictionary of selected fields.
     * reverse - boolean, True if we are checking a reverse join
    """
    from plain.postgres.fields.related import RelatedField

    if not isinstance(field, RelatedField):
        return False
    if restricted:
        assert requested is not None, "requested must be provided when restricted=True"
        if reverse and field.related_query_name() not in requested:
            return False
        if not reverse and field.name not in requested:
            return False
    if not restricted and field.allow_null:
        return False
    if (
        restricted
        and select_mask
        and field.name in requested  # ty: ignore[unsupported-operator]
        and field not in select_mask
    ):
        raise FieldError(
            f"Field {field.model.model_options.object_name}.{field.name} cannot be both "
            "deferred and traversed using join() at the same time."
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
    model: type[Model], target_meta: Meta, field: Field | ForeignObjectRel
) -> bool:
    """
    Check that model is compatible with target_meta — i.e. model matches
    the target's model, or the field is a primary key whose model matches.
    """

    def check(meta: Meta) -> bool:
        return model == meta.model

    # Primary-key fields get a second chance: a queryset like
    # `Model.query.filter(id__in=Model.query.all())` resolves `id__in` through
    # the PK field, whose target meta is the remote model. Allow the match
    # against the field's own model so the subquery (later reduced to
    # `.values("id")`) is accepted.
    return check(target_meta) or (
        getattr(field, "primary_key", False) and check(field.model._model_meta)
    )
