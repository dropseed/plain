from __future__ import annotations

from plain import postgres
from plain.passwords.types import PasswordField
from plain.postgres import types


@postgres.register_model
class User(postgres.Model):
    email: str = types.EmailField()
    password: str = PasswordField()

    query: postgres.QuerySet[User] = postgres.QuerySet()

    def __str__(self) -> str:
        return self.email
