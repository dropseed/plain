from __future__ import annotations

from typing import ClassVar

from plain import models
from plain.models import types
from plain.passwords.types import PasswordField


@models.register_model
class User(models.Model):
    email: str = types.EmailField()
    password: str = PasswordField()
    is_admin: bool = types.BooleanField(default=False)

    query: ClassVar[models.QuerySet[User]] = models.QuerySet()
