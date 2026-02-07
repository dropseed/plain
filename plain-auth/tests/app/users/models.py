from plain.models import types

from plain import models


@models.register_model
class User(models.Model):
    username: str = types.CharField(max_length=255)
    is_admin: bool = types.BooleanField(default=False)
