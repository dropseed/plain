from __future__ import annotations

from datetime import datetime

from plain import postgres
from plain.postgres import types
from plain.runtime import SettingsReference


@postgres.register_model
class PinnedNavItem(postgres.Model):
    """A user's pinned navigation item in the admin."""

    user = types.ForeignKeyField(
        SettingsReference("AUTH_USER_MODEL"),
        on_delete=postgres.CASCADE,
    )
    view_slug: str = types.TextField(max_length=255)
    order: int = types.SmallIntegerField(default=0)
    created_at: datetime = types.DateTimeField(auto_now_add=True)

    query: postgres.QuerySet[PinnedNavItem] = postgres.QuerySet()

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
