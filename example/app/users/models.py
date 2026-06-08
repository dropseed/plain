from __future__ import annotations

from datetime import datetime

from plain import postgres
from plain.passwords.types import PasswordField
from plain.postgres import Field, types


@postgres.register_model
class User(postgres.Model):
    email: Field[str] = types.EmailField()
    password: Field[str] = PasswordField()
    is_admin: Field[bool] = types.BooleanField(default=False)
    created_at: Field[datetime] = types.DateTimeField(create_now=True)
