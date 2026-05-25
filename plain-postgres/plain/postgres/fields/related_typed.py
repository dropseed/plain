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

    Known limitation — descriptor attribute shadowing
    -------------------------------------------------
    For the first hop, `Child.parent` is the FK descriptor itself.
    `__getattr__` only fires when normal attribute lookup *fails*, so if a
    related model defines a field whose name collides with a public
    attribute on `ForwardForeignKeyDescriptor` — currently `field`,
    `is_cached`, `get_queryset`, `get_prefetch_queryset`, or
    `RelatedObjectDoesNotExist` — `Child.parent.<that_name>` silently
    returns the descriptor's attribute instead of building a `PrefixedFieldRef`.
    The typed-where call against it then produces wrong SQL.

    The architectural fix is to return a fresh proxy object from
    `ForwardForeignKeyDescriptor.__get__(instance=None)` instead of `self`,
    so the descriptor's own attributes aren't reachable through class
    access. That's a bigger change with a wider blast radius (framework
    code reads `Child.parent.field` etc.) and is deferred.
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
        self._reject_if_blocked("equals")
        return self._q("", value)

    def not_equal(self, value: Any) -> Q:
        self._reject_if_blocked("not_equal")
        return ~self._q("", value)

    def gt(self, value: Any) -> Q:
        self._reject_if_blocked("gt")
        return self._q("gt", value)

    def gte(self, value: Any) -> Q:
        self._reject_if_blocked("gte")
        return self._q("gte", value)

    def lt(self, value: Any) -> Q:
        self._reject_if_blocked("lt")
        return self._q("lt", value)

    def lte(self, value: Any) -> Q:
        self._reject_if_blocked("lte")
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
        self._reject_if_blocked("contains")
        return self._q("contains", value)

    def icontains(self, value: str) -> Q:
        self._reject_if_blocked("icontains")
        return self._q("icontains", value)

    def startswith(self, value: str) -> Q:
        self._reject_if_blocked("startswith")
        return self._q("startswith", value)

    def endswith(self, value: str) -> Q:
        self._reject_if_blocked("endswith")
        return self._q("endswith", value)

    def _q(self, suffix: str, value: Any) -> Q:
        key = f"{self._prefix}__{suffix}" if suffix else self._prefix
        q = Q()
        q.children.append((key, value))
        return q

    def _reject_if_blocked(self, method_name: str) -> None:
        """Forward the typed-query block from fields that reject value
        comparisons (currently EncryptedFieldMixin). Direct access raises
        TypeError at the call site; without this hook, traversing through
        a relation (Order.user.api_token.equals(...)) would silently build
        a Q that only errors later at SQL build time."""
        from plain.postgres.fields.encrypted import EncryptedFieldMixin

        if isinstance(self._field, EncryptedFieldMixin):
            field_name = getattr(self._field, "name", None) or "<encrypted>"
            raise TypeError(
                f"Encrypted field {field_name!r} (reached via "
                f"{self._prefix!r}) does not support .{method_name}() — "
                "ciphertext is non-deterministic. Use .is_null() instead."
            )
