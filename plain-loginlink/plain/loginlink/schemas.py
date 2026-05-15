from __future__ import annotations

from plain.schema import Schema, types


class LoginLinkSchema(Schema):
    """Validates the email (and optional `next` redirect) submitted to request
    a login link. Pure data — sending the link lives in the view."""

    email: str = types.EmailField()
    next: str | None = types.TextField(required=False)
