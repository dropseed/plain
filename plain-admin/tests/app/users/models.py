from __future__ import annotations

from plain import models
from plain.models import types


@models.register_model
class User(models.Model):
    username: str = types.CharField(max_length=255)
    is_admin: bool = types.BooleanField(default=False)

    query: models.QuerySet[User] = models.QuerySet()
