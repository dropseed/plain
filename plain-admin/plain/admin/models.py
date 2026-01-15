from __future__ import annotations

from datetime import datetime

from plain import models
from plain.models import types
from plain.runtime import SettingsReference


@models.register_model
class PinnedNavItem(models.Model):
    """A user's pinned navigation item in the admin."""

    user = types.ForeignKeyField(
        SettingsReference("AUTH_USER_MODEL"),
        on_delete=models.CASCADE,
    )
    view_slug: str = types.CharField(max_length=255)
    order: int = types.SmallIntegerField(default=0)
    created_at: datetime = types.DateTimeField(auto_now_add=True)

    query: models.QuerySet[PinnedNavItem] = models.QuerySet()

    model_options = models.Options(
        constraints=[
            models.UniqueConstraint(
                fields=["user", "view_slug"],
                name="plainadmin_pinnednavitem_unique_user_view",
            )
        ],
        ordering=["order", "created_at"],
    )

    def __str__(self) -> str:
        return f"{self.user} - {self.view_slug}"
