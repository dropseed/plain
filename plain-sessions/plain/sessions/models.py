from __future__ import annotations

from datetime import datetime

from plain import postgres
from plain.postgres import Field, types

__all__ = ["Session"]


@postgres.register_model
class Session(postgres.Model):
    session_key: Field[str] = types.TextField(max_length=40)
    session_data: Field[dict] = types.JSONField(default={}, required=False)
    created_at: Field[datetime] = types.DateTimeField(create_now=True)
    expires_at: Field[datetime | None] = types.DateTimeField(
        allow_null=True, default=None
    )

    model_options = postgres.Options(
        indexes=[
            postgres.Index(
                name="plainsessions_session_expires_at_idx", fields=["expires_at"]
            ),
        ],
        constraints=[
            postgres.UniqueConstraint(fields=["session_key"], name="unique_session_key")
        ],
    )

    def __str__(self) -> str:
        return self.session_key
