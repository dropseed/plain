from __future__ import annotations

from plain import models
from plain.passwords.models import PasswordField


@models.register_model
class User(models.Model):
    email: str = models.EmailField()
    password: str = PasswordField()
    is_admin: bool = models.BooleanField(default=False)
