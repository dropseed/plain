from __future__ import annotations

import datetime
from typing import Any

from plain import models


@models.register_model
class Session(models.Model):
    session_key: str = models.CharField(max_length=40)
    session_data: dict[str, Any] = models.JSONField(default=dict, required=False)
    created_at: datetime.datetime = models.DateTimeField(auto_now_add=True)
    expires_at: datetime.datetime | None = models.DateTimeField(allow_null=True)

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
