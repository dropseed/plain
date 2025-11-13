from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from plain.exceptions import ValidationError
from plain.models import (
    CASCADE,
    BooleanField,
    CharField,
    DateTimeField,
    Field,
    ForeignKey,
    JSONField,
    Model,
    Options,
    TextField,
    UniqueConstraint,
    register_model,
)


def validate_flag_name(value: str) -> None:
    if not re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", value):
        raise ValidationError(f"{value} is not a valid Python identifier name")


@register_model
class Flag(Model):
    created_at: Field[datetime] = DateTimeField(auto_now_add=True)
    updated_at: Field[datetime] = DateTimeField(auto_now=True)
    name: Field[str] = CharField(max_length=255, validators=[validate_flag_name])

    # Optional description that can be filled in after the flag is used/created
    description: Field[str] = TextField(required=False)

    # To manually disable a flag before completing deleting
    # (good to disable first to make sure the code doesn't use the flag anymore)
    enabled: Field[bool] = BooleanField(default=True)

    # To provide an easier way to see if a flag is still being used
    used_at: Field[datetime | None] = DateTimeField(required=False, allow_null=True)

    model_options = Options(
        constraints=[
            UniqueConstraint(fields=["name"], name="plainflags_flag_unique_name"),
        ],
    )

    def __str__(self) -> str:
        return self.name


@register_model
class FlagResult(Model):
    created_at: Field[datetime] = DateTimeField(auto_now_add=True)
    updated_at: Field[datetime] = DateTimeField(auto_now=True)
    flag: Field[Flag] = ForeignKey(Flag, on_delete=CASCADE)
    key: Field[str] = CharField(max_length=255)
    value: Field[Any] = JSONField()

    model_options = Options(
        constraints=[
            UniqueConstraint(
                fields=["flag", "key"], name="plainflags_flagresult_unique_key"
            ),
        ],
    )

    def __str__(self) -> str:
        return self.key
