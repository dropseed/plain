from plain.postgres import Field, types

from plain import postgres


@postgres.register_model
class User(postgres.Model):
    username: Field[str] = types.TextField(max_length=255)
    is_admin: Field[bool] = types.BooleanField(default=False)

    def get_avatar_url(self) -> str:
        """The admin header renders this when the user model provides it."""
        return f"https://avatars.example.com/{self.username}.png"

    @property
    def username_upper(self) -> str:
        """A computed (non-column) field, to exercise in-memory sorting."""
        return self.username.upper()
