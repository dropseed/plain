from __future__ import annotations

from plain import postgres
from plain.postgres import Field, types


@postgres.register_model
class IterationExample(postgres.Model):
    """Minimal model for bulk-insert + iterator tests.

    Two text fields so `.values()` / `.values_list()` have something to
    return beyond `id`. Shared by a handful of tests that only need "a
    writable table with some rows" (iterator, read-only, exception
    class plumbing).
    """

    name: Field[str] = types.TextField(max_length=100)
    tag: Field[str] = types.TextField(max_length=100)
