"""Typed FK traversal for the where() query API.

When `Order.user` is a ForeignKey, accessing `.email` at the class level (as in
`where(Order.user.email.equals("x"))`) needs to produce `Q(user__email="x")` so
the existing SQL builder's join machinery resolves the right column.

The whole mechanism is `Field.with_lookup_prefix`: walking into the related
model hands back that model's own field, renamed to carry the relation path, so
its own condition methods build the right keys. Nothing here re-implements or
rewrites a field's surface -- which is why a traversed field offers exactly
what direct access offers, down to an encrypted field's blocks.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from plain.postgres.constants import LOOKUP_SEP
from plain.postgres.exceptions import FieldDoesNotExist
from plain.postgres.fields.base import CONDITION_METHODS
from plain.postgres.fields.related import ForeignKeyField

if TYPE_CHECKING:
    from plain.postgres.base import Model


class RelatedFieldRef:
    """Class-level proxy that walks attribute access into the related model and
    accumulates the lookup-path prefix as it goes.

    Chained traversal (`Order.user.profile.city`) builds nested
    `RelatedFieldRef` instances until a concrete field is reached, which comes
    back as a prefixed copy of that field.

    Names resolve through the related model's metadata (`get_forward_field`),
    not attribute lookup, so a related field keeps resolving to the field.

    A relation is not itself a field, so it carries no condition methods.
    `Child.parent.equals(obj)` is spelled `Child.parent.id.equals(obj.id)` --
    traversal to the key the relation targets, which compiles to the same
    `parent__id=` lookup `filter(parent=obj)` produces. This can't be smoothed
    over by adding the methods here: to the type checker `Child.parent` is
    `type[Parent]` (see `Field.__get__`'s model-valued overloads), which is
    what makes chained traversal type-check, and a runtime method the checker
    rejects would be worse than no method at all. `__getattr__` raises an
    AttributeError pointing at the right spelling instead.
    """

    def __init__(self, model: type[Model], prefix: str, target_name: str) -> None:
        assert not isinstance(model, str), (
            "RelatedFieldRef requires a resolved model class; the FK's "
            "remote_field.model is replaced with the class at registration."
        )
        self._model = model
        self._prefix = prefix
        # The field on the related model that this relation targets -- the hop
        # a condition on the relation has to go through.
        self._target_name = target_name

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
            # The field lookup comes first so a related model that really does
            # have a column named `equals` (or `contains`, …) still traverses
            # to it. An AttributeError, not a TypeError, so `hasattr` and
            # `getattr(..., default)` keep behaving.
            if name in CONDITION_METHODS:
                raise AttributeError(
                    f"{self._prefix}.{name}() is not available: "
                    f"{self._prefix!r} is a relation, not a field. Build the "
                    f"condition on the key it points at instead -- "
                    f"{self._prefix}.{self._target_name}.{name}(...), which "
                    f"compiles to the same SQL."
                ) from None
            raise AttributeError(
                f"{self._prefix}.{name} is not a traversable field or relation"
            ) from None

        if isinstance(field, ForeignKeyField):
            return RelatedFieldRef(
                model=field.remote_field.model,
                prefix=f"{self._prefix}{LOOKUP_SEP}{name}",
                target_name=field.target_field.name,
            )
        return field.with_lookup_prefix(self._prefix)
