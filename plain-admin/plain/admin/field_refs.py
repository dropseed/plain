"""Field references in admin declarations.

`search_fields`, `queryset_order` and a `TrendCard`'s datetime/group fields are
declared as either a typed field reference (`User.email`, or the traversed
`FlagResult.flag.name`) or the lookup path as a string. Both spellings are
normalized to the path, so every query site downstream builds the same
`Q(**{f"{path}__icontains": ...})` / `order_by(path)` it always built -- the
SQL is identical whichever spelling the declaration used.

Normalizing happens twice, for two different reasons:

- **At class definition**, over a plain tuple (or a plain `Field`/`str`) found
  on the class. That is where a reference to another model's field can be
  refused while the traceback still points at the declaration -- and it also
  takes the `Field` back off the class attribute. A `Field` is a data
  descriptor, so one left sitting on a view or card class would run on every
  `self.search_fields`, which is not what the attribute means there.
- **At runtime**, over whatever the instance actually has. A declaration can
  be a `property`, or replaced on the instance from `get()`, and neither goes
  through class definition.

Strings stay supported because not every path is expressible as a reference:
traversal has to *start* at a forward foreign key, so a path that starts at a
reverse accessor or a many-to-many (`"memberships__team__name"`) has no field
to reference.
"""

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

    if not ref.lookup_path:
        # A field declared on a `ModelMixin`, or built standalone for an
        # aggregate, was never named -- only the model that mixes it in has an
        # attached copy. Left alone it normalizes to "" and surfaces much
        # later as `FieldError: Cannot resolve keyword ''`.
        raise TypeError(
            f"{declared_as} references an unattached "
            f"{type(ref).__name__} -- a field declared on a mixin, or built "
            f"on its own, carries no name to look up. Reference the field on "
            f"the model that declares it."
        )

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


def _declared(obj: Any, attr: str) -> Any:
    """Read `attr` off a class or instance without running a descriptor.

    Class definition has to see the declaration itself, not what `Field`'s
    descriptor would hand back; an instance read has to see its own override
    rather than the class default. `getattr_static` does both.
    """
    return inspect.getattr_static(obj, attr, None)


def converge_declared_tuple(cls: type, attr: str, *, model: type[Model] | None) -> None:
    """Normalize a tuple of field references declared on `cls`, in place.

    Anything that isn't a plain tuple -- a `property`, a method, a descriptor
    of someone else's -- is left alone; it computes its value per instance, so
    it is normalized at runtime instead.
    """
    raw = _declared(cls, attr)
    if not isinstance(raw, tuple):
        return

    paths = field_lookup_paths(
        raw, model=model, declared_as=f"{cls.__qualname__}.{attr}"
    )
    if paths != raw:
        setattr(cls, attr, paths)


def converge_declared_field(cls: type, attr: str, *, model: type[Model] | None) -> None:
    """Normalize a single field reference declared on `cls`, in place."""
    raw = _declared(cls, attr)
    if not isinstance(raw, Field | str):
        return

    path = field_lookup_path(raw, model=model, declared_as=f"{cls.__qualname__}.{attr}")
    if path != raw:
        setattr(cls, attr, path)


def instance_field_ref(obj: Any, attr: str) -> FieldRef | None:
    """Read a single `FieldRef | None` declaration off a live instance.

    The static read is what picks up an instance's own override. Anything it
    finds that isn't a reference already is something that computes one -- a
    `property`, say -- so that one is asked for normally.
    """
    ref = _declared(obj, attr)
    if ref is None or isinstance(ref, Field | str):
        return ref
    return getattr(obj, attr)
