from __future__ import annotations

import datetime

from plain import postgres
from plain.passwords.types import PasswordField
from plain.postgres import types


@postgres.register_model
class User(postgres.Model):
    email: str = types.EmailField()
    password: str = PasswordField()
    is_admin: bool = types.BooleanField(default=False)
    created_at: datetime.datetime = types.CreatedAtField()

    query: postgres.QuerySet[User] = postgres.QuerySet()
