from __future__ import annotations

from typing import TYPE_CHECKING

from plain import postgres
from plain.postgres import types

if TYPE_CHECKING:
    from plain.oauth.models import OAuthConnection


@postgres.register_model
class User(postgres.Model):
    email: str = types.EmailField()
    username: str = types.CharField(max_length=100)

    # Explicit reverse relation for OAuth connections
    oauth_connections: types.ReverseForeignKey[OAuthConnection] = (
        types.ReverseForeignKey(to="plainoauth.OAuthConnection", field="user")
    )

    query: postgres.QuerySet[User] = postgres.QuerySet()

    model_options = postgres.Options(
        constraints=[
            postgres.UniqueConstraint(fields=["email"], name="user_unique_email"),
            postgres.UniqueConstraint(fields=["username"], name="user_unique_username"),
        ],
    )

    def __str__(self) -> str:
        return self.username
