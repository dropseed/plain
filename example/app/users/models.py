from __future__ import annotations

from plain.models import BooleanField, EmailField, Field, Model, register_model
from plain.passwords.models import PasswordField


@register_model
class User(Model):
    email: Field[str] = EmailField()
    password: Field[str] = PasswordField()
    is_admin: Field[bool] = BooleanField(default=False)
