from __future__ import annotations

import re
from datetime import datetime

from plain import postgres
from plain.exceptions import ValidationError
from plain.postgres import Field, types

__all__ = ["Flag", "FlagResult"]


def validate_flag_name(value: str) -> None:
    if not re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", value):
        raise ValidationError(f"{value} is not a valid Python identifier name")


@postgres.register_model
class FlagResult(postgres.Model):
    created_at: Field[datetime] = types.DateTimeField(create_now=True)
    updated_at: Field[datetime] = types.DateTimeField(create_now=True, update_now=True)
    flag: Flag = types.ForeignKeyField("Flag", on_delete=postgres.CASCADE)
    key: Field[str] = types.TextField(max_length=255)
    value: Field[dict] = types.JSONField()

    model_options = postgres.Options(
        constraints=[
            postgres.UniqueConstraint(
                fields=["flag", "key"], name="plainflags_flagresult_unique_key"
            ),
        ],
    )

    def __str__(self) -> str:
        return self.key


@postgres.register_model
class Flag(postgres.Model):
    created_at: Field[datetime] = types.DateTimeField(create_now=True)
    updated_at: Field[datetime] = types.DateTimeField(create_now=True, update_now=True)
    name: Field[str] = types.TextField(max_length=255, validators=[validate_flag_name])

    # Optional description that can be filled in after the flag is used/created
    description: Field[str] = types.TextField(required=False)

    # To manually disable a flag before completing deleting
    # (good to disable first to make sure the code doesn't use the flag anymore)
    enabled: Field[bool] = types.BooleanField(default=True)

    # To provide an easier way to see if a flag is still being used
    used_at: Field[datetime | None] = types.DateTimeField(
        required=False, allow_null=True, default=None
    )

    model_options = postgres.Options(
        constraints=[
            postgres.UniqueConstraint(
                fields=["name"], name="plainflags_flag_unique_name"
            ),
        ],
    )

    def __str__(self) -> str:
        return self.name
