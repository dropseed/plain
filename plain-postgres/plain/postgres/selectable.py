"""The common base for anything `select()` can pull back as a column.

`Field[T]` carries a real value type and subclasses `Selectable[T]`, so a
field contributes its `T` to the selected row. Expressions subclass
`Selectable[Any]` — they stay un-generic for now and contribute `Any`, which is
honest (an aggregate's output type isn't tracked yet) and can be tightened later
without touching `select()`.

The overload ladder on `QuerySet.select()` binds each argument's `T` through
this shared base. For the type checker to solve that per-column typevar, `T`
must appear in an *annotated member* of `Selectable[T]` — a bare `class
Selectable[T]: pass` gives it nothing to unify against inside an overloaded
method on a generic class. `__plain_selected_type__` is that member; it exists
only under `TYPE_CHECKING` and is never called.

Because `Field` and the SQL `Query` clone themselves with the
`Empty()` + `__class__`-reassignment trick, adding `Selectable` to their bases
shifts their C-level "solid base". The stand-in `Empty` classes those clones
start from therefore subclass `Selectable` too, so the reassignment stays
layout-compatible.
"""

from __future__ import annotations

from typing import TYPE_CHECKING


class Selectable[T]:
    if TYPE_CHECKING:
        # Reference T in an annotated member so ty can solve the per-column
        # typevar when select()'s overload ladder is keyed on Selectable[T].
        def __plain_selected_type__(self) -> T: ...
