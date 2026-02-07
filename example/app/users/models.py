from __future__ import annotations

import datetime

from plain import models
from plain.models import types
from plain.passwords.types import PasswordField


@models.register_model
class User(models.Model):
    email: str = types.EmailField()
    password: str = PasswordField()
    is_admin: bool = types.BooleanField(default=False)
    created_at: datetime.datetime = types.DateTimeField(auto_now_add=True)

    query: models.QuerySet[User] = models.QuerySet()
