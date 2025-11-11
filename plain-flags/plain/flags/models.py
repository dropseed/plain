from __future__ import annotations

import datetime
import re
from typing import Any

from plain import models
from plain.exceptions import ValidationError


def validate_flag_name(value: str) -> None:
    if not re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", value):
        raise ValidationError(f"{value} is not a valid Python identifier name")


@models.register_model
class FlagResult(models.Model):
    created_at: datetime.datetime = models.DateTimeField(auto_now_add=True)
    updated_at: datetime.datetime = models.DateTimeField(auto_now=True)
    flag: Flag = models.ForeignKey("Flag", on_delete=models.CASCADE)
    key: str = models.CharField(max_length=255)
    value: Any = models.JSONField()

    model_options = models.Options(
        constraints=[
            models.UniqueConstraint(
                fields=["flag", "key"], name="plainflags_flagresult_unique_key"
            ),
        ],
    )

    def __str__(self) -> str:
        return self.key


@models.register_model
class Flag(models.Model):
    created_at: datetime.datetime = models.DateTimeField(auto_now_add=True)
    updated_at: datetime.datetime = models.DateTimeField(auto_now=True)
    name: str = models.CharField(max_length=255, validators=[validate_flag_name])

    # Optional description that can be filled in after the flag is used/created
    description: str = models.TextField(required=False)

    # To manually disable a flag before completing deleting
    # (good to disable first to make sure the code doesn't use the flag anymore)
    enabled: bool = models.BooleanField(default=True)

    # To provide an easier way to see if a flag is still being used
    used_at: datetime.datetime | None = models.DateTimeField(
        required=False, allow_null=True
    )

    model_options = models.Options(
        constraints=[
            models.UniqueConstraint(
                fields=["name"], name="plainflags_flag_unique_name"
            ),
        ],
    )

    def __str__(self) -> str:
        return self.name
