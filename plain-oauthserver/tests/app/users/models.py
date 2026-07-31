from __future__ import annotations

from plain import postgres
from plain.postgres import Field, types


@postgres.register_model
class User(postgres.Model):
    email: Field[str] = types.EmailField()
    password: Field[str] = types.TextField(max_length=128, required=False)

    model_options = postgres.Options(
        constraints=[
            postgres.UniqueConstraint(fields=["email"], name="user_unique_email"),
        ],
    )

    def __str__(self) -> str:
        return self.email
