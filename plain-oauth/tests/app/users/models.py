from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from plain import postgres
from plain.postgres import Field, types

if TYPE_CHECKING:
    from plain.oauth.models import OAuthConnection


@postgres.register_model
class User(postgres.Model):
    email: Field[str] = types.EmailField()
    username: Field[str] = types.TextField(max_length=100)

    # Explicit reverse relation for OAuth connections
    oauth_connections: ClassVar[types.ReverseForeignKey[OAuthConnection]] = (
        types.ReverseForeignKey(to="plainoauth.OAuthConnection", field="user")
    )

    model_options = postgres.Options(
        constraints=[
            postgres.UniqueConstraint(fields=["email"], name="user_unique_email"),
            postgres.UniqueConstraint(fields=["username"], name="user_unique_username"),
        ],
    )

    def __str__(self) -> str:
        return self.username
