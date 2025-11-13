from __future__ import annotations

from datetime import datetime
from typing import Any

from plain.models import (
    CharField,
    DateTimeField,
    Field,
    Index,
    JSONField,
    Model,
    Options,
    UniqueConstraint,
    register_model,
)


@register_model
class Session(Model):
    session_key: Field[str] = CharField(max_length=40)
    session_data: Field[dict[str, Any]] = JSONField(default=dict, required=False)
    created_at: Field[datetime] = DateTimeField(auto_now_add=True)
    expires_at: Field[datetime | None] = DateTimeField(allow_null=True)

    model_options = Options(
        indexes=[
            Index(fields=["expires_at"]),
        ],
        constraints=[
            UniqueConstraint(fields=["session_key"], name="unique_session_key")
        ],
    )

    def __str__(self) -> str:
        return self.session_key
