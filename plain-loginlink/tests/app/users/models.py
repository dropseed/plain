from __future__ import annotations

from plain.postgres import types

from plain import postgres


@postgres.register_model
class User(postgres.Model):
    email = types.EmailField()

    query: postgres.QuerySet[User] = postgres.QuerySet()

    def __str__(self) -> str:
        return self.email
