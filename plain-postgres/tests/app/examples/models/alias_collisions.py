from __future__ import annotations

from plain.postgres import Field, types

from plain import postgres


@postgres.register_model
class AliasCollisionExample(postgres.Model):
    """A model whose column names look like generated expression aliases.

    `select(Upper(...))` names its column `upper1` and `select(F(...))` names
    its column `f1`, so a model that already has columns by those names is
    what proves the generator skips them rather than shadowing a real column.
    """

    name: Field[str] = types.TextField(max_length=100)
    upper1: Field[str] = types.TextField(max_length=100, required=False, default="")
    f1: Field[str] = types.TextField(max_length=100, required=False, default="")
