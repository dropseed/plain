from __future__ import annotations

from typing import Any

from plain import models

from . import validators
from .hashers import (
    hash_password,
    identify_hasher,
)


class PasswordField(models.CharField):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        kwargs["max_length"] = 128
        kwargs.setdefault(
            "validators",
            [
                validators.MinimumLengthValidator(),
                validators.CommonPasswordValidator(),
                validators.NumericPasswordValidator(),
            ],
        )
        super().__init__(*args, **kwargs)

    def deconstruct(self) -> tuple[str, str, tuple[Any, ...], dict[str, Any]]:
        name, path, args, kwargs = super().deconstruct()
        if kwargs.get("max_length") == 128:
            del kwargs["max_length"]
        return name, path, tuple(args), kwargs

    def pre_save(self, model_instance: models.Model, add: bool) -> str:
        value = super().pre_save(model_instance, add)

        if value and not self._is_hashed(value):
            value = hash_password(value)
            # Set the hashed value back on the instance immediately too
            setattr(model_instance, self.attname, value)

        return value

    @staticmethod
    def _is_hashed(value: str) -> bool:
        try:
            identify_hasher(value)
            return True
        except ValueError:
            return False
