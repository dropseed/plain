from __future__ import annotations

from plain.postgres import types

from plain import postgres


@postgres.register_model
class ShadowTarget(postgres.Model):
    """Related model whose field names collide with public attributes on
    ForwardForeignKeyDescriptor. Traversal through the FK must resolve these
    to the fields, not the descriptor's own attributes."""

    field = types.TextField(max_length=100)
    is_cached = types.TextField(max_length=100)
    get_queryset = types.TextField(max_length=100)
    get_prefetch_queryset = types.TextField(max_length=100)

    query: postgres.QuerySet[ShadowTarget] = postgres.QuerySet()


@postgres.register_model
class ShadowSource(postgres.Model):
    ref = types.ForeignKeyField(ShadowTarget, on_delete=postgres.CASCADE)

    query: postgres.QuerySet[ShadowSource] = postgres.QuerySet()
