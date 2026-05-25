"""Typed FK traversal for the where() query API.

When `Order.user` is a ForeignKey, accessing `.email` at the class level (as in
`where(Order.user.email.equals("x"))`) needs to produce
`Q(user__email="x")` so the existing SQL builder's join machinery resolves the
right column. The descriptor doesn't expose the related model's fields directly,
so we proxy attribute access through these two helpers.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from plain.postgres.query_utils import Q

if TYPE_CHECKING:
    from plain.postgres.base import Model


class RelatedFieldRef:
    """Class-level proxy that walks attribute access into the related model
    and accumulates the lookup path prefix as it goes.

    Yielded by `ForwardForeignKeyDescriptor.__getattr__` for the first hop;
    chained traversal (`Order.user.profile.city`) builds nested
    `RelatedFieldRef` instances until a concrete field is reached.
    """

    def __init__(self, model: type[Model], prefix: str) -> None:
        self._model = model
        self._prefix = prefix

    def __repr__(self) -> str:
        return f"<RelatedFieldRef {self._prefix} → {self._model.__name__}>"

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_"):
            # Avoid infinite recursion on internals and let pickling/hasattr
            # checks fail cleanly.
            raise AttributeError(name)
        from plain.postgres.fields.base import Field
        from plain.postgres.fields.related_descriptors import (
            ForwardForeignKeyDescriptor,
        )

        try:
            attr = self._model.__dict__[name]
        except KeyError:
            # Fall back to a full lookup so inherited fields resolve.
            attr = getattr(self._model, name, None)
            if attr is None:
                raise AttributeError(name) from None

        next_prefix = f"{self._prefix}__{name}"
        if isinstance(attr, Field):
            return PrefixedFieldRef(field=attr, prefix=next_prefix)
        if isinstance(attr, ForwardForeignKeyDescriptor):
            remote_model = attr.field.remote_field.model
            if isinstance(remote_model, str):
                raise AttributeError(
                    f"Cannot traverse {self._prefix}.{name}: relation is "
                    "still a string reference; the related model has not "
                    "been registered yet."
                )
            return RelatedFieldRef(model=remote_model, prefix=next_prefix)
        raise AttributeError(
            f"{self._prefix}.{name} is not a traversable field or relation"
        )


class PrefixedFieldRef:
    """A field-like reference that produces Q objects with a multi-segment
    lookup path. Mirrors the typed-query method surface of `Field` and
    `TextField` so chained access reads identically to direct access:

        Order.user.email.equals("x")    # PrefixedFieldRef("user__email")
        Order.email.equals("x")         # Field/TextField on Order
    """

    def __init__(self, field: Any, prefix: str) -> None:
        self._field = field
        self._prefix = prefix

    def __repr__(self) -> str:
        return f"<PrefixedFieldRef {self._prefix}>"

    # Mirror Field[T] typed-query methods. Lookup suffixes match the strings
    # the base Field methods produce via _build_q, so SQL resolution is the
    # same as for a direct field reference.
    def equals(self, value: Any) -> Q:
        return self._q("", value)

    def not_equal(self, value: Any) -> Q:
        return ~self._q("", value)

    def gt(self, value: Any) -> Q:
        return self._q("gt", value)

    def gte(self, value: Any) -> Q:
        return self._q("gte", value)

    def lt(self, value: Any) -> Q:
        return self._q("lt", value)

    def lte(self, value: Any) -> Q:
        return self._q("lte", value)

    def is_null(self, value: bool = True) -> Q:
        return self._q("isnull", value)

    # TextField-specific lookups — always exposed at the proxy layer because
    # callers go through the typing lie (`Order.user.email` reads as
    # TextField[str] to the type checker). At runtime, calling .contains on
    # a non-text field's PrefixedFieldRef would build SQL that errors at
    # query time, which is the same failure mode as a manual
    # `filter(user__priority__contains=...)`.
    def contains(self, value: str) -> Q:
        return self._q("contains", value)

    def icontains(self, value: str) -> Q:
        return self._q("icontains", value)

    def startswith(self, value: str) -> Q:
        return self._q("startswith", value)

    def endswith(self, value: str) -> Q:
        return self._q("endswith", value)

    def _q(self, suffix: str, value: Any) -> Q:
        key = f"{self._prefix}__{suffix}" if suffix else self._prefix
        q = Q()
        q.children.append((key, value))
        return q
