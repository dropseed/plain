from plain.postgres import Field, types

from plain import postgres


@postgres.register_model
class TreeNode(postgres.Model):
    """Self-referential FK for testing convergence with circular references."""

    name: Field[str] = types.TextField(max_length=100)
    parent: Field[TreeNode | None] = types.ForeignKeyField(
        "self", on_delete=postgres.CASCADE, allow_null=True, default=None
    )
