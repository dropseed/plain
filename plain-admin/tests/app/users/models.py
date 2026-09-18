from __future__ import annotations

from plain.postgres import Field, types

from plain import postgres


@postgres.register_model
class User(postgres.Model):
    username: Field[str] = types.TextField(max_length=255)
    is_admin: Field[bool] = types.BooleanField(default=False)

    @property
    def username_upper(self) -> str:
        """A computed (non-column) field, to exercise in-memory sorting."""
        return self.username.upper()
