from __future__ import annotations

from datetime import datetime
from typing import ClassVar

from plain import models
from plain.models import types


@models.register_model
class Session(models.Model):
    session_key: str = types.CharField(max_length=40)
    session_data: dict = types.JSONField(default=dict, required=False)
    created_at: datetime = types.DateTimeField(auto_now_add=True)
    expires_at: datetime | None = types.DateTimeField(allow_null=True)

    query: ClassVar[models.QuerySet[Session]] = models.QuerySet()

    model_options = models.Options(
        indexes=[
            models.Index(fields=["expires_at"]),
        ],
        constraints=[
            models.UniqueConstraint(fields=["session_key"], name="unique_session_key")
        ],
    )

    def __str__(self) -> str:
        return self.session_key
