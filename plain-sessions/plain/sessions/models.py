from __future__ import annotations

from plain.models import (
    CharField,
    DateTimeField,
    Index,
    JSONField,
    Model,
    Options,
    UniqueConstraint,
    register_model,
)


@register_model
class Session(Model):
    session_key = CharField(max_length=40)
    session_data = JSONField(default=dict, required=False)
    created_at = DateTimeField(auto_now_add=True)
    expires_at = DateTimeField(allow_null=True)

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
