"""Typed FK traversal for the where() query API.

When `Order.user` is a ForeignKey, accessing `.email` at the class level (as in
`where(Order.user.email.equals("x"))`) needs to produce
`Q(user__email="x")` so the existing SQL builder's join machinery resolves the
right column. `ForwardForeignKeyDescriptor.__get__` returns a `RelatedFieldRef`
for class-level access, and these two helpers walk attribute access into the
related model to build the lookup path.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from plain.postgres.exceptions import FieldDoesNotExist
from plain.postgres.fields.related import ForeignKeyField
from plain.postgres.query_utils import Q

if TYPE_CHECKING:
    from plain.postgres.base import Model
    from plain.postgres.fields.base import Field


# Condition-method names a traversed field exposes. Traversal offers exactly the
# surface the field itself offers: an attribute outside this set is not a
# condition method and raises AttributeError rather than silently building a
# wrong-shaped Q.
_CONDITION_METHODS = frozenset(
    {
        "equals",
        "not_equal",
        "gt",
        "gte",
        "lt",
        "lte",
        "is_null",
        "is_in",
        "contains",
        "icontains",
        "startswith",
        "endswith",
    }
)


def _prefix_q(q: Q, parent_path: str) -> Q:
    """Prepend `parent_path__` to every leaf lookup key in a Q tree, in place.

    A leaf child is a `(key, value)` tuple; a nested Q node is recursed into.
    Negation and connector are left untouched — only the lookup keys change,
    turning a Q built against a field's bare name into one whose keys carry the
    full relation path.
    """
    for i, child in enumerate(q.children):
        if isinstance(child, Q):
            _prefix_q(child, parent_path)
        else:
            key, value = child
            q.children[i] = (f"{parent_path}__{key}", value)
    return q


class RelatedFieldRef:
    """Class-level proxy that walks attribute access into the related model and
    accumulates the lookup-path prefix as it goes.

    Returned by `ForwardForeignKeyDescriptor.__get__` for the first hop; chained
    traversal (`Order.user.profile.city`) builds nested `RelatedFieldRef`
    instances until a concrete field is reached, then a `PrefixedFieldRef`.

    Names resolve through the related model's metadata (`get_forward_field`),
    not attribute lookup, so a related field whose name collides with a public
    attribute on the FK descriptor (`field`, `is_cached`, `get_queryset`, …)
    still resolves to that field.
    """

    def __init__(self, model: type[Model], prefix: str) -> None:
        assert not isinstance(model, str), (
            "RelatedFieldRef requires a resolved model class; the FK's "
            "remote_field.model is replaced with the class at registration."
        )
        self._model = model
        self._prefix = prefix

    def __repr__(self) -> str:
        return f"<RelatedFieldRef {self._prefix} → {self._model.__name__}>"

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_"):
            # Avoid infinite recursion on internals and let pickling/hasattr
            # checks fail cleanly.
            raise AttributeError(name)

        try:
            field = self._model._model_meta.get_forward_field(name)
        except FieldDoesNotExist:
            raise AttributeError(
                f"{self._prefix}.{name} is not a traversable field or relation"
            ) from None

        if isinstance(field, ForeignKeyField):
            return RelatedFieldRef(
                model=field.remote_field.model, prefix=f"{self._prefix}__{name}"
            )
        return PrefixedFieldRef(field=field, parent_path=self._prefix)


class PrefixedFieldRef:
    """A field-like reference that rewrites the wrapped field's own Q conditions
    onto a multi-segment lookup path, so chained access reads identically to
    direct access:

        Order.user.email.equals("x")    # PrefixedFieldRef(email_field, "user")
        Order.email.equals("x")         # TextField on Order

    A condition call delegates to the wrapped field's own method (which builds a
    Q against the field's bare name, or raises — e.g. an encrypted field), then
    prefixes every leaf key in that Q with the parent relation path. The
    traversed surface is therefore exactly the field's own surface: a method the
    field doesn't define raises AttributeError, same as direct access.
    """

    def __init__(self, field: Field, parent_path: str) -> None:
        self._field = field
        self._parent_path = parent_path

    def __repr__(self) -> str:
        return f"<PrefixedFieldRef {self._parent_path}__{self._field.name}>"

    def __getattr__(self, name: str) -> Any:
        if name not in _CONDITION_METHODS:
            raise AttributeError(name)
        field_method = getattr(self._field, name)

        def build(*args: Any, **kwargs: Any) -> Q:
            return _prefix_q(field_method(*args, **kwargs), self._parent_path)

        return build
