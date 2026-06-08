from __future__ import annotations

from datetime import datetime

from app.users.models import User

from plain import postgres
from plain.postgres import Field, types


@postgres.register_model
class PinnedNavItem(postgres.Model):
    """A user's pinned navigation item in the admin."""

    user: User = types.ForeignKeyField(
        "users.User",
        on_delete=postgres.CASCADE,
    )
    view_slug: Field[str] = types.TextField(max_length=255)
    order: Field[int] = types.SmallIntegerField(default=0)
    created_at: Field[datetime] = types.DateTimeField(create_now=True)

    model_options = postgres.Options(
        constraints=[
            postgres.UniqueConstraint(
                fields=["user", "view_slug"],
                name="plainadmin_pinnednavitem_unique_user_view",
            )
        ],
        ordering=["order", "created_at"],
    )

    def __str__(self) -> str:
        return f"{self.user} - {self.view_slug}"
