"""The common base for anything `select()` can pull back as a column.

`Field[T]` carries a real value type and subclasses `Selectable[T]`, so a
field contributes its `T` to the selected row. Expressions subclass
`Selectable[Any]` — they stay un-generic for now and contribute `Any`, which is
honest (an aggregate's output type isn't tracked yet) and can be tightened later
without touching `select()`.

The overload ladder on `QuerySet.select()` binds each argument's `T` through
this shared base. A type checker resolves `T` per argument against a common base
class, but not through a `Field[T] | Expression[T]` union — hence the single
base rather than a union.

Because `Field` and the SQL `Query` clone themselves with the
`Empty()` + `__class__`-reassignment trick, adding `Selectable` to their bases
shifts their C-level "solid base". The stand-in `Empty` classes those clones
start from therefore subclass `Selectable` too, so the reassignment stays
layout-compatible.
"""

from __future__ import annotations


class Selectable[T]:
    pass
