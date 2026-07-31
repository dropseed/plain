from __future__ import annotations

from plain import postgres
from plain.passwords.types import PasswordField
from plain.postgres import Field, types


@postgres.register_model
class User(postgres.Model):
    email: Field[str] = types.EmailField()
    password: Field[str] = PasswordField()

    def __str__(self) -> str:
        return self.email
