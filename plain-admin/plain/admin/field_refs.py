"""Field references in admin declarations.

`search_fields`, `queryset_order` and a `TrendCard`'s datetime/group fields are
declared as either a typed field reference (`User.email`, or the traversed
`FlagResult.flag.name`) or the lookup path as a string. Both spellings are
normalized to the path here, once, so every query site downstream builds the
same `Q(**{f"{path}__icontains": ...})` / `order_by(path)` it always built --
the SQL is identical whichever spelling the declaration used.

Strings stay supported because not every path is expressible as a reference:
traversal starts at a forward foreign key, so reverse and many-to-many paths
(`"memberships__team__name"`) have no field to reference.
"""

from __future__ import annotations

import inspect
from typing import Any

from plain.postgres import Field, Model

# What a field-taking admin declaration accepts.
type FieldRef = Field[Any] | str


def field_lookup_path(
    ref: FieldRef, *, model: type[Model] | None, declared_as: str
) -> str:
    """Normalize one declared reference to its lookup path.

    `model` is the model the declaring view or card queries, or None when
    there is nothing to check against (an `AdminListView` over plain objects).
    `declared_as` names the declaration in the error, e.g.
    `"UserAdmin.ListView.search_fields"`.
    """
    if isinstance(ref, str):
        return ref

    # A field reference carries the model a condition built from it would
    # belong to -- the declaring model for a column, the model the traversal
    # started from for `FlagResult.flag.name`. The same identity where()
    # checks, checked here instead, because these declarations are turned into
    # string lookups and would otherwise resolve silently against the wrong
    # column.
    source = ref.source_model
    if model is not None and source is not None and source is not model:
        raise TypeError(
            f"{declared_as} references {source.__name__}.{ref.lookup_path}, "
            f"but this is a {model.__name__} view. Reference "
            f"{model.__name__}'s own field, or traverse to it from "
            f"{model.__name__}."
        )

    return ref.lookup_path


def field_lookup_paths(
    refs: tuple[FieldRef, ...], *, model: type[Model] | None, declared_as: str
) -> tuple[str, ...]:
    """Normalize a declared tuple of references to lookup paths."""
    return tuple(
        field_lookup_path(ref, model=model, declared_as=declared_as) for ref in refs
    )


def declared_field_ref(cls: type, attr: str) -> FieldRef | None:
    """Read a `FieldRef | None` declaration off `cls` without the descriptor.

    A `Field` is a descriptor, so `SomeCard.datetime_field` would run
    `Field.__get__`. That is harmless at runtime -- class access hands the
    field straight back -- but a field is typed as a *model's* descriptor, so
    a checker rejects reading one off a card or a view. `getattr_static`
    returns the declaration itself, which is what the declaration means.
    """
    return inspect.getattr_static(cls, attr, None)
