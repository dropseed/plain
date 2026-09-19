from __future__ import annotations

from plain.postgres import Field, types

from plain import postgres


@postgres.register_model
class ShadowTarget(postgres.Model):
    """Related model whose field names collide with public attributes on
    ForwardForeignKeyDescriptor. Traversal through the FK must resolve these
    to the fields, not the descriptor's own attributes."""

    field: Field[str] = types.TextField(max_length=100)
    is_cached: Field[str] = types.TextField(max_length=100)
    get_queryset: Field[str] = types.TextField(max_length=100)
    get_prefetch_queryset: Field[str] = types.TextField(max_length=100)


@postgres.register_model
class ShadowSource(postgres.Model):
    ref: Field[ShadowTarget] = types.ForeignKeyField(
        ShadowTarget, on_delete=postgres.CASCADE
    )
