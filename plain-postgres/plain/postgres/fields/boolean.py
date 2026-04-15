from __future__ import annotations

from typing import Any

from plain import exceptions

from .base import DefaultableField


class BooleanField(DefaultableField[bool]):
    db_type_sql = "boolean"
    empty_strings_allowed = False
    default_error_messages = {
        "invalid": '"%(value)s" value must be either True or False.',
        "invalid_nullable": '"%(value)s" value must be either True, False, or None.',
    }
    description = "Boolean (Either True or False)"

    def to_python(self, value: Any) -> bool | None:
        if self.allow_null and value in self.empty_values:
            return None
        if value in (True, False):
            # 1/0 are equal to True/False. bool() converts former to latter.
            return bool(value)
        if value in ("t", "True", "1"):
            return True
        if value in ("f", "False", "0"):
            return False
        raise exceptions.ValidationError(
            self.error_messages["invalid_nullable" if self.allow_null else "invalid"],
            code="invalid",
            params={"value": value},
        )

    def get_prep_value(self, value: Any) -> Any:
        value = super().get_prep_value(value)
        if value is None:
            return None
        return self.to_python(value)
