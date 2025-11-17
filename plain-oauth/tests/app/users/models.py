from __future__ import annotations

from typing import TYPE_CHECKING

from plain import models
from plain.models import types

if TYPE_CHECKING:
    from plain.oauth.models import OAuthConnection


@models.register_model
class User(models.Model):
    email: str = types.EmailField()
    username: str = types.CharField(max_length=100)

    # Explicit reverse relation for OAuth connections
    oauth_connections: types.ReverseForeignKey[OAuthConnection] = (
        types.ReverseForeignKey(to="plainoauth.OAuthConnection", field="user")
    )

    query: models.QuerySet[User] = models.QuerySet()

    model_options = models.Options(
        constraints=[
            models.UniqueConstraint(fields=["email"], name="user_unique_email"),
            models.UniqueConstraint(fields=["username"], name="user_unique_username"),
        ],
    )

    def __str__(self) -> str:
        return self.username
