from __future__ import annotations

from plain.postgres import types

from plain import postgres


@postgres.register_model
class User(postgres.Model):
    email = types.EmailField()
    password = types.TextField(max_length=128, required=False, default="")

    query: postgres.QuerySet[User] = postgres.QuerySet()

    model_options = postgres.Options(
        constraints=[
            postgres.UniqueConstraint(fields=["email"], name="user_unique_email"),
        ],
    )

    def __str__(self) -> str:
        return self.email
