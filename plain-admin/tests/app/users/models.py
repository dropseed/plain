from __future__ import annotations

from plain.postgres import types

from plain import postgres


@postgres.register_model
class User(postgres.Model):
    username = types.TextField(max_length=255)
    is_admin = types.BooleanField(default=False)

    query: postgres.QuerySet[User] = postgres.QuerySet()

    def get_avatar_url(self) -> str:
        """The admin header renders this when the user model provides it."""
        return f"https://avatars.example.com/{self.username}.png"

    @property
    def username_upper(self) -> str:
        """A computed (non-column) field, to exercise in-memory sorting."""
        return self.username.upper()
