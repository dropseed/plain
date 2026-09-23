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

from typing import TYPE_CHECKING, Any

from plain.postgres.constants import LOOKUP_SEP
from plain.postgres.exceptions import FieldDoesNotExist
from plain.postgres.fields.base import CONDITION_METHODS
from plain.postgres.fields.related import RelatedField
from plain.postgres.fields.reverse_descriptors import (
    ReverseForeignKey,
    ReverseManyToMany,
)

if TYPE_CHECKING:
    from plain.postgres.base import Model


class UnresolvedRelationError(AttributeError):
    """A traversal reached a relation whose target model isn't resolved yet.

    An AttributeError subclass so `hasattr` and `getattr(..., default)` keep
    working, but a distinct type so the timing problem is greppable rather
    than looking like a typo.
    """


class RelatedFieldRef:
    """Class-level proxy that walks attribute access into the related model and
    accumulates the lookup-path prefix as it goes.

    Chained traversal (`Order.user.profile.city`) builds nested
    `RelatedFieldRef` instances until a concrete field is reached, which comes
    back as a prefixed copy of that field. Every relation is a hop -- many-to-
    many included, since `widget__tags__name` is as valid a lookup path as
    `widget__author__name`.

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

    def __init__(
        self,
        model: type[Model],
        prefix: str,
        target_name: str,
        source_model: type[Model],
    ) -> None:
        if isinstance(model, str):
            raise unresolved_relation_error(prefix, model)
        self._model = model
        self._prefix = prefix
        # The field on the related model that this relation targets -- the hop
        # a condition on the relation has to go through.
        self._target_name = target_name
        # The model the traversal started from, carried unchanged through every
        # hop: a condition on `Order.user.profile.city` belongs to `Order`.
        self._source_model = source_model

    def __repr__(self) -> str:
        return f"<RelatedFieldRef {self._prefix} → {self._model.__name__}>"

    def _is_reverse_relation(self, name: str) -> bool:
        """Whether `name` names a reverse accessor on the related model.

        Reverse accessors live on the class as descriptors, not in the field
        metadata, so both places are checked.
        """
        try:
            self._model._model_meta.get_reverse_relation(name)
        except FieldDoesNotExist:
            return isinstance(
                getattr(self._model, name, None),
                (ReverseForeignKey, ReverseManyToMany),
            )
        return True

    @property
    def _attribute_path(self) -> str:
        """The prefix spelled the way it was written -- `widget.tags`, not
        `widget__tags` -- so error messages can be pasted back into code."""
        return self._prefix.replace(LOOKUP_SEP, ".")

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
            # to it. Every failure below is an AttributeError, not a TypeError,
            # so `hasattr` and `getattr(..., default)` keep behaving.
            if name in CONDITION_METHODS:
                raise AttributeError(
                    f"{self._attribute_path}.{name}() is not available: "
                    f"{self._prefix!r} is a relation, not a field. Build the "
                    f"condition on the key it points at instead -- "
                    f"{self._attribute_path}.{self._target_name}.{name}(...), "
                    f"which compiles to the same SQL."
                ) from None
            if self._is_reverse_relation(name):
                raise AttributeError(
                    f"{self._attribute_path}.{name} is a reverse relation, "
                    f"which the typed API cannot traverse: a reverse accessor "
                    f"is a ClassVar, so there is nothing for "
                    f"`{self._model.__name__}` to offer the type checker here. "
                    f"Use the string path instead -- "
                    f"filter({self._prefix}{LOOKUP_SEP}{name}{LOOKUP_SEP}...=...)."
                ) from None
            raise AttributeError(
                f"{self._attribute_path}.{name} is not a traversable field or relation"
            ) from None

        if isinstance(field, RelatedField):
            # Any relation is another hop, foreign key or many-to-many alike --
            # `widget__tags__name` is as valid a lookup path as
            # `widget__author__name`. Handing back the relation field itself
            # would rename it to "widget__tags" and then let `.name` resolve to
            # that string.
            return RelatedFieldRef(
                model=field.remote_field.model,
                prefix=f"{self._prefix}{LOOKUP_SEP}{name}",
                target_name=field.target_field.name,
                source_model=self._source_model,
            )
        return field.with_lookup_prefix(self._prefix, self._source_model)


def unresolved_relation_error(prefix: str, target: str) -> UnresolvedRelationError:
    """The error for a traversal that outran model registration.

    Relation targets are replaced with the resolved class when the model
    registers, so a traversal evaluated at import time -- at module level, or
    in a default argument -- can run before the registry is populated.
    """
    return UnresolvedRelationError(
        f"Cannot traverse {prefix!r}: its target model {target!r} hasn't been "
        f"resolved yet. Relation targets are resolved when the model is "
        f"registered, so this traversal is running too early -- move it inside "
        f"the function or method that needs it."
    )
