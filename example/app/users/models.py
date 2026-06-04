from __future__ import annotations

from plain import postgres
from plain.passwords.types import PasswordField
from plain.postgres import types


@postgres.register_model
class User(postgres.Model):
    email = types.EmailField()
    password: str = PasswordField()
    is_admin = types.BooleanField(default=False)
    created_at = types.DateTimeField(create_now=True)

    query: postgres.QuerySet[User] = postgres.QuerySet()
