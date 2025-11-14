from plain import models
from plain.models import types
from plain.passwords.models import PasswordField


@models.register_model
class User(models.Model):
    email: str = types.EmailField()
    password = PasswordField()
    is_admin: bool = types.BooleanField(default=False)
