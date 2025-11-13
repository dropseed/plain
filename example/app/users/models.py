from __future__ import annotations

from plain.models import BooleanField, EmailField, Model, register_model
from plain.passwords.models import PasswordField


@register_model
class User(Model):
    email = EmailField()
    password = PasswordField()
    is_admin = BooleanField(default=False)
