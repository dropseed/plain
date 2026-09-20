"""The common base for anything `select()` can pull back as a column.

`Field[T]` carries a real value type and subclasses `Selectable[T]`, so a
field contributes its `T` to the selected row. Expressions subclass
`Selectable[Any]` — they stay un-generic for now and contribute `Any`, which is
honest (an aggregate's output type isn't tracked yet) and can be tightened later
without touching `select()`.

The overload ladder on `QuerySet.select()` binds each argument's `T` through
this shared base: a checker solves `T0` from `Field[str] <: Selectable[T0]` by
specializing the base class, so the marker needs no members of its own. The
ladder's per-column types are asserted in `tests/typing/select_rows.py`, which
is what would catch a checker that can't.
"""

from __future__ import annotations


class Selectable[T]:
    pass
