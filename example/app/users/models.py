from __future__ import annotations

from datetime import datetime

from plain.passwords.values import HashedPassword
from plain.postgres import Field, types

from plain import postgres


@postgres.register_model
class User(postgres.Model):
    email: Field[str] = types.EmailField()
    password: Field[HashedPassword] = types.TextField(value_type=HashedPassword)
    is_admin: Field[bool] = types.BooleanField(default=False)
    created_at: Field[datetime] = types.DateTimeField(create_now=True)
