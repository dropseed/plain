from __future__ import annotations

from datetime import datetime

from plain import postgres
from plain.postgres import types

__all__ = ["Session"]


@postgres.register_model
class Session(postgres.Model):
    session_key: str = types.CharField(max_length=40)
    session_data: dict = types.JSONField(default=dict, required=False)
    created_at: datetime = types.DateTimeField(auto_now_add=True)
    expires_at: datetime | None = types.DateTimeField(allow_null=True)

    query: postgres.QuerySet[Session] = postgres.QuerySet()

    model_options = postgres.Options(
        indexes=[
            postgres.Index(fields=["expires_at"]),
        ],
        constraints=[
            postgres.UniqueConstraint(fields=["session_key"], name="unique_session_key")
        ],
    )

    def __str__(self) -> str:
        return self.session_key
