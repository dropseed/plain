from __future__ import annotations

from plain import postgres
from plain.postgres import types


@postgres.register_model
class TreeNode(postgres.Model):
    """Self-referential FK for testing convergence with circular references."""

    name: str = types.TextField(max_length=100)
    parent: TreeNode | None = types.ForeignKeyField(
        "self", on_delete=postgres.CASCADE, allow_null=True
    )
    parent_id: int | None

    query: postgres.QuerySet[TreeNode] = postgres.QuerySet()
